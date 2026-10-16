import { advanceTime, expect, test, tick } from "@odoo/hoot";
import { Component, xml } from "@odoo/owl";
import {
    destroyApp,
    mockService,
    mountWithCleanup,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { Geolocation } from "@web_enterprise/core/geolocation/geolocation";

async function mountGeolocation() {
    let geolocation;
    class Parent extends Component {
        static template = xml``;
        setup() {
            geolocation = new Geolocation();
        }
    }
    await mountWithCleanup(Parent);
    return geolocation;
}

test("geolocatePartners caches the coordinates even if its owner is destroyed", async () => {
    const requestDeferred = Promise.withResolvers();
    onRpc("https://nominatim.openstreetmap.org/*", async () => {
        expect.step("osm request");
        await requestDeferred.promise;
        return [{ display_name: "Grand-Rosière", lon: "4", lat: "50" }];
    });
    onRpc("res.partner", "update_latitude_longitude", ({ args }) => {
        expect.step("update_latitude_longitude");
        expect(args[0]).toEqual([
            {
                id: 1,
                contact_address_complete: "Grand-Rosière",
                partner_latitude: 50,
                partner_longitude: 4,
            },
        ]);
        return true;
    });

    const geolocation = await mountGeolocation();
    const partner = { id: 1, contact_address_complete: "Grand-Rosière" };
    const geolocated = geolocation.geolocatePartners(partner);
    await expect.waitForSteps(["osm request"]);

    // The owner is destroyed (e.g. switching to another view) before the provider answers.
    destroyApp();
    requestDeferred.resolve();
    await geolocated;

    await expect.waitForSteps(["update_latitude_longitude"]);
});

test("geolocatePartners requests each address once and only for partners to locate", async () => {
    onRpc("https://nominatim.openstreetmap.org/*", (request) => {
        expect.step(request.url);
        return [{ display_name: "Somewhere", lon: "4", lat: "50" }];
    });
    onRpc("res.partner", "update_latitude_longitude", ({ args }) => {
        expect.step(`update_latitude_longitude: ${args[0].map((partner) => partner.id)}`);
        return true;
    });

    const geolocation = await mountGeolocation();
    await geolocation.geolocatePartners(
        [
            // same address: requested only once
            { id: 1, contact_address_complete: "A" },
            { id: 2, contact_address_complete: "A" },
            // valid coordinates: not requested
            { id: 3, contact_address_complete: "B", partner_latitude: 51, partner_longitude: 5 },
            // invalid coordinates: requested again
            { id: 4, contact_address_complete: "C", partner_latitude: 100, partner_longitude: 5 },
            // nothing to request, but still counted as processed
            { id: 5, contact_address_complete: "" },
        ],
        () => expect.step("partner processed")
    );

    // OpenStreetMap requests are sent one per second, so each one is processed before the next
    await expect.waitForSteps([
        "partner processed",
        "https://nominatim.openstreetmap.org/search?q=A&format=jsonv2",
        "partner processed",
        "https://nominatim.openstreetmap.org/search?q=C&format=jsonv2",
        "partner processed",
        "update_latitude_longitude: 1,2,4",
    ]);
});

test("geolocatePartners does not write partners for which no coordinates were found", async () => {
    onRpc("https://nominatim.openstreetmap.org/*", (request) => {
        expect.step(request.url);
        return [];
    });
    onRpc("res.partner", "update_latitude_longitude", () => {
        expect.step("update_latitude_longitude");
    });

    const geolocation = await mountGeolocation();
    const partner = { id: 1, contact_address_complete: "Nowhere" };
    await geolocation.geolocatePartners(partner);

    expect.verifySteps([
        "https://nominatim.openstreetmap.org/search?q=Nowhere&format=jsonv2",
    ]);
    expect(partner.partner_latitude).toBe(undefined);
    expect(partner.partner_longitude).toBe(undefined);
});

test("_fetchCoordinatesFromAddressOSM converts an address into coordinates", async () => {
    onRpc("https://nominatim.openstreetmap.org/*", (request) => {
        expect.step(request.url);
        return [{ display_name: "Grand-Rosière", lat: "50.2", lon: "4.1" }];
    });

    const geolocation = await mountGeolocation();

    expect(await geolocation._fetchCoordinatesFromAddressOSM("Grand-Rosière")).toEqual([
        { address: "Grand-Rosière", latitude: 50.2, longitude: 4.1 },
    ]);
    expect.verifySteps([
        "https://nominatim.openstreetmap.org/search?q=Grand-Rosi%C3%A8re&format=jsonv2",
    ]);
});

test("_fetchCoordinatesFromAddressOSM no longer requests OpenStreetMap after a failure", async () => {
    mockService("notification", {
        add(message) {
            expect.step(`notification: ${message}`);
        },
    });
    onRpc("https://nominatim.openstreetmap.org/*", (request) => {
        expect.step(request.url);
        throw new Error("Too Many Requests");
    });

    const geolocation = await mountGeolocation();

    expect(await geolocation._fetchCoordinatesFromAddressOSM("A")).toEqual([]);
    expect.verifySteps([
        "https://nominatim.openstreetmap.org/search?q=A&format=jsonv2",
        "notification: OpenStreetMap's request limit exceeded, try again later.",
    ]);

    expect(await geolocation._fetchCoordinatesFromAddressOSM("B")).toEqual([]);
    expect.verifySteps([]);
});

test("_fetchAddressFromCoordinatesOSM converts coordinates into an address", async () => {
    onRpc("https://nominatim.openstreetmap.org/*", (request) => {
        expect.step(request.url);
        return {
            address: {
                road: "Sweet Street",
                house_number: "12",
                city: "Somewhere",
                postcode: "1000",
                state: "Brussels",
                country: "Belgium",
            },
        };
    });

    const geolocation = await mountGeolocation();

    expect(await geolocation._fetchAddressFromCoordinatesOSM(50.85, 4.35)).toEqual({
        street: "Sweet Street",
        house_number: "12",
        city: "Somewhere",
        zip: "1000",
        state: "Brussels",
        country: "Belgium",
    });
    expect.verifySteps([
        "https://nominatim.openstreetmap.org/reverse?lat=50.85&lon=4.35&format=jsonv2",
    ]);
});

test("_fetchAddressFromCoordinatesOSM no longer requests OpenStreetMap after a failure", async () => {
    mockService("notification", {
        add(message) {
            expect.step(`notification: ${message}`);
        },
    });
    onRpc("https://nominatim.openstreetmap.org/*", (request) => {
        expect.step(request.url);
        throw new Error("Too Many Requests");
    });

    const geolocation = await mountGeolocation();

    expect(await geolocation._fetchAddressFromCoordinatesOSM(50.85, 4.35)).toEqual({});
    expect.verifySteps([
        "https://nominatim.openstreetmap.org/reverse?lat=50.85&lon=4.35&format=jsonv2",
        "notification: OpenStreetMap's request limit exceeded, try again later.",
    ]);

    expect(await geolocation._fetchAddressFromCoordinatesOSM(40.21, 5.65)).toEqual({});
    expect.verifySteps([]);
});

test("searchCoordinatesFromAddress uses OpenStreetMap", async () => {
    const geolocation = await mountGeolocation();
    patchWithCleanup(geolocation, {
        async _fetchCoordinatesFromAddressOSM(address) {
            expect.step(`osm: ${address}`);
            return [];
        },
    });

    await geolocation.searchCoordinatesFromAddress("A");
    expect.verifySteps(["osm: A"]);
});

test("searchAddressFromCoordinates uses OpenStreetMap", async () => {
    const geolocation = await mountGeolocation();
    patchWithCleanup(geolocation, {
        async _fetchAddressFromCoordinatesOSM(lat, lon) {
            expect.step(`osm: ${lat},${lon}`);
            return {};
        },
    });

    await geolocation.searchAddressFromCoordinates(50.85, 4.35);
    expect.verifySteps(["osm: 50.85,4.35"]);
});

test("OpenStreetMap requests are sent once per second", async () => {
    const geolocation = await mountGeolocation();
    patchWithCleanup(geolocation, {
        async _fetchCoordinatesFromAddressOSM(address) {
            expect.step(address);
            return [];
        },
    });

    geolocation.searchCoordinatesFromAddress("A");
    geolocation.searchCoordinatesFromAddress("B");
    geolocation.searchCoordinatesFromAddress("C");

    await tick();
    expect.verifySteps(["A"]);
    await advanceTime(1000);
    expect.verifySteps(["B"]);
    await advanceTime(1000);
    expect.verifySteps(["C"]);
});

test("stopFetchingCoordinates drops the OpenStreetMap requests left in the queue", async () => {
    const geolocation = await mountGeolocation();
    patchWithCleanup(geolocation, {
        async _fetchCoordinatesFromAddressOSM(address) {
            expect.step(address);
            return [];
        },
    });

    geolocation.searchCoordinatesFromAddress("A");
    geolocation.searchCoordinatesFromAddress("B");
    geolocation.searchCoordinatesFromAddress("C");
    await tick();
    expect.verifySteps(["A"]);

    geolocation.stopFetchingCoordinates();
    await advanceTime(2000);
    expect.verifySteps([]);
});

test("OpenStreetMap requests queued right after stopFetchingCoordinates are still sent once per second", async () => {
    const geolocation = await mountGeolocation();
    patchWithCleanup(geolocation, {
        async _fetchCoordinatesFromAddressOSM(address) {
            expect.step(address);
            return [];
        },
    });

    geolocation.searchCoordinatesFromAddress("A");
    geolocation.searchCoordinatesFromAddress("B");
    await tick();
    expect.verifySteps(["A"]);

    geolocation.stopFetchingCoordinates();
    await advanceTime(200);
    geolocation.searchCoordinatesFromAddress("X");
    geolocation.searchCoordinatesFromAddress("Y");
    geolocation.searchCoordinatesFromAddress("Z");
    await advanceTime(800);
    expect.verifySteps(["X"]);
    await advanceTime(1000);
    expect.verifySteps(["Y"]);
    await advanceTime(1000);
    expect.verifySteps(["Z"]);
});
