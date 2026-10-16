import { _t } from "@web/core/data/l10n/translation";
import { delay } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";

function hasValidCoordinates(partner) {
    return (
        partner.partner_latitude &&
        partner.partner_longitude &&
        partner.partner_latitude >= -90 &&
        partner.partner_latitude <= 90 &&
        partner.partner_longitude >= -180 &&
        partner.partner_longitude <= 180
    );
}

/**
 * Geolocation service handling address translation (from and to coordinates) and partner geocoding.
 * It uses OpenStreetMap (https://nominatim.org/) and includes built-in sequential queue throttling
 * for its requests to avoid getting banned from the API.
 */
export class Geolocation {
    static OSM_COORDINATE_FETCH_DELAY = 1000;

    constructor() {
        this.http = useService("http");
        this.orm = useService("orm");
        this.notification = useService("notification");

        this._osmQueue = [];
        this._isProcessingQueue = false;
        this._waitProm = Promise.resolve();

        this.allowFetchOSM = true;
    }

    /**
     * Fetches coordinates of an address using OpenStreetMap.
     *
     * @param {string} address
     * @returns {Promise<Array<{address: string, latitude: number, longitude: number}>>} Promise of list of Objects ordered by relevance. Values closer to 1 mean closer match to the input
     */
    async searchCoordinatesFromAddress(address) {
        const { promise, resolve } = Promise.withResolvers();
        this._osmQueue.push(() => this._fetchCoordinatesFromAddressOSM(address).then(resolve));
        this._processOSMQueue();
        return promise;
    }
    /**
     * Fetches the address of coordinates using OpenStreetMap.
     *
     * @param {number} lat latitude
     * @param {number} lon longitude
     * @returns {Promise<{street: string, house_number: string, city: string, zip: string, state: string, country: string}>} Promise containing the fetched address Object
     */
    async searchAddressFromCoordinates(lat, lon) {
        const { promise, resolve } = Promise.withResolvers();
        this._osmQueue.push(() => this._fetchAddressFromCoordinatesOSM(lat, lon).then(resolve));
        this._processOSMQueue();
        return promise;
    }
    /**
     * Geolocates partners (i.e., finding their coordinates) based on their address.
     *
     * @param {Array<{contact_address_complete: string, partner_latitude: number, partner_longitude: number}>} partners
     * @param {Function|undefined} onPartnerGeolocated optional callback to be executed every time a partner is geolocated
     * @returns {Promise<void>} Resolves when all partners have been geolocated and results written in db
     */
    async geolocatePartners(partners, onPartnerGeolocated) {
        if (!Array.isArray(partners)) {
            partners = [partners];
        }
        // Group partners by address to reduce address list
        const addressPartnerMap = new Map();
        for (const partner of partners) {
            if (!hasValidCoordinates(partner)) {
                partner.partner_latitude = undefined;
                partner.partner_longitude = undefined;
                if (!partner.contact_address_complete) {
                    onPartnerGeolocated?.();
                }
            }
            if (
                partner.contact_address_complete &&
                (!partner.partner_latitude || !partner.partner_longitude)
            ) {
                if (!addressPartnerMap.has(partner.contact_address_complete)) {
                    addressPartnerMap.set(partner.contact_address_complete, []);
                }
                addressPartnerMap.get(partner.contact_address_complete).push(partner);
            }
        }
        if (addressPartnerMap.size === 0) {
            return;
        }

        const partnersToCache = [];
        const promises = [...addressPartnerMap].map(async ([address, partners]) => {
            const coordinates = await this.searchCoordinatesFromAddress(address);
            if (coordinates.length) {
                for (const partner of partners) {
                    partner.partner_longitude = coordinates[0].longitude;
                    partner.partner_latitude = coordinates[0].latitude;
                    partnersToCache.push(partner);
                }
            }
            onPartnerGeolocated?.();
        });
        await Promise.all(promises);
        this._writePartnersLatitudeLongitude(partnersToCache);
    }
    /**
     * Tells the service to stop fetching coordinates.
     * The service fetches coordinates once every second, as OpenStreetMap otherwise bans the client.
     * There are typically two cases when we need to stop fetching:
     * - when component is about to be unmounted because the request is bound to
     *   the component and it will crash if we do so.
     * - when calling the `load` method as it will start fetching new coordinates.
     */
    stopFetchingCoordinates() {
        this._osmQueue = [];
    }

    //----------------------------------------------------------------------
    // Private
    //----------------------------------------------------------------------

    /**
     * OpenStreetMap only allows one request per second so we ensure to wait 1 second between each request.
     * @private
     */
    async _processOSMQueue() {
        if (this._isProcessingQueue) {
            return;
        }
        this._isProcessingQueue = true;
        while (this._osmQueue.length) {
            await this._waitProm;
            // dequeue after waiting, as the queue may have been cleared in the meantime
            const request = this._osmQueue.shift();
            if (request) {
                this._waitProm = delay(this.constructor.OSM_COORDINATE_FETCH_DELAY);
                request();
            }
        }
        this._isProcessingQueue = false;
    }
    /**
     * @private
     */
    async _writePartnersLatitudeLongitude(partners) {
        partners = partners.filter(hasValidCoordinates);
        if (partners.length) {
            await this.orm.unscoped.call("res.partner", "update_latitude_longitude", [partners]);
        }
    }
    /**
     * Converts the addresses to coordinates using the openStreetMap API.
     *
     * @private
     * @param {String} address
     * @returns {Promise<Array<Object>>} promise resolving to an array of addresses and coordinates, ordered by descending relevance
     */
    async _fetchCoordinatesFromAddressOSM(address) {
        if (!this.allowFetchOSM) {
            return [];
        }
        const encodedAddress = encodeURIComponent(address.replace("/", " "));
        const encodedUrl = `https://nominatim.openstreetmap.org/search?q=${encodedAddress}&format=jsonv2`;
        const res = await this.http.get(encodedUrl).catch(() => this._osmErrorHandling());
        if (!res?.length) {
            return [];
        }
        return res.map((r) => ({
            address: r.display_name,
            longitude: parseFloat(r.lon),
            latitude: parseFloat(r.lat),
        }));
    }
    /**
     * Converts the coordinates to addresses using the openStreetMap API.
     *
     * @private
     * @param {number} lat latitude
     * @param {number} lon longitude
     * @returns {Promise<Object>} promise resolving to an address object
     */
    async _fetchAddressFromCoordinatesOSM(lat, lon) {
        if (!this.allowFetchOSM) {
            return {};
        }
        const encodedUrl = `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=jsonv2`;
        const res = await this.http.get(encodedUrl).catch(() => this._osmErrorHandling());
        if (!res?.address) {
            return {};
        }
        return {
            street: res.address.road,
            house_number: res.address.house_number,
            city: res.address.city,
            zip: res.address.postcode,
            state: res.address.state,
            country: res.address.country,
        };
    }
    /**
     * Handles the displaying of error message according to the error.
     *
     * @private
     */
    _osmErrorHandling() {
        this.allowFetchOSM = false;
        this.notification.add(_t("OpenStreetMap's request limit exceeded, try again later."), {
            type: "danger",
        });
    }
}
