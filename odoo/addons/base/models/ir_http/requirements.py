# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ----------------------------------------------------------
# ir_http authentication requirements
# ----------------------------------------------------------
import typing


class AuthRequirements(typing.TypedDict, total=False):
    logout: bool
    """True if a full login is required."""

    check_identity: bool
    """True if an identity check is required."""

    mfa: bool
    """True if multi-factor authentication is required."""

    first_fa_method: str
    """
    Previously used first-factor authentication method.
    Used to avoid reusing the same method as a second factor.
    """

    fingerprint_check: bool
    """
    True if re-authentication can be fully completed
    using the device fingerprint alone.
    """


class CheckIdentityResult(typing.TypedDict, total=False):
    auth_methods: list[str]
    """
    List of available authentication methods.
    Present when no credential is provided, or when an additional
    authentication factor is required.
    """

    mfa: bool
    """True if a second authentication factor is required."""
