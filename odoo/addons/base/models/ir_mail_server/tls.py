# Part of Odoo. See LICENSE file for full copyright and licensing details.
from urllib3.contrib.pyopenssl import get_subj_alt_name
try:
    # urllib3 1.26 (ubuntu jammy and up, debian bullseye and up)
    from urllib3.util.ssl_match_hostname import match_hostname
except ImportError:
    # urllib3 1.25 and below
    from urllib3.packages.ssl_match_hostname import match_hostname


def _verify_check_hostname_callback(cnx, x509, err_no, err_depth, return_code, *, hostname):
    """Callback used for pyOpenSSL.verify_mode, by default pyOpenSSL
       only checkes :param:`err_no`, we enrich it to also verify that
       the SMTP server :param:`hostname` matches the :param:`x509`'s
       Common Name (CN) or Subject Alternative Name (SAN)."""
    if err_no:
        return False

    if err_depth == 0:  # leaf certificate
        peercert = {
            "subject": ((("commonName", x509.get_subject().CN),),),
            "subjectAltName": get_subj_alt_name(x509),
        }
        match_hostname(peercert, hostname)  # it raises when it does not match

    return True
