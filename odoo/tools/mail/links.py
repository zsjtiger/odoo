"""Links of the messages: the URL patterns, the validation of the URLs and the links of the text."""

import re
from urllib.parse import urlparse
from werkzeug import urls


URL_SKIP_PROTOCOL_REGEX = r'mailto:|tel:|sms:'


URL_REGEX = rf'''(\bhref=['"](?!{URL_SKIP_PROTOCOL_REGEX})([^'"]+)['"])'''


TEXT_URL_ALLOWED_GROUP = r'[\w@:%+&~#=/-]|[.,][^\s](?!$)'  # defines what characters can be inside a URL


TEXT_URL_REGEX = r'https?://'  # scheme


TEXT_URL_REGEX += rf'(?:{TEXT_URL_ALLOWED_GROUP})+'  # domain + path


TEXT_URL_REGEX += r'(?:\?(?:[^\s.,]|[.,][^\s](?!$))+)?'  # query parameters


def validate_url(url):
    if urls.url_parse(url).scheme not in ('http', 'https', 'ftp', 'ftps'):
        return 'http://' + url

    return url


def url_domain_extract(url):
    """ Extract the company domain to be used by IAP services notably. Domain
    is extracted from an URL e.g:

    - www.info.proximus.be -> proximus.be
    """
    parser_results = urlparse(url)
    company_hostname = parser_results.hostname
    if company_hostname and '.' in company_hostname:
        return '.'.join(company_hostname.split('.')[-2:])  # remove subdomains
    return False


def text_url_replace(original_url, new_url, text):
    """Replace an url with another inside some arbitrary text. Avoids matching sub-urls."""
    return re.sub(re.escape(original_url) + rf'(?!{TEXT_URL_ALLOWED_GROUP})', new_url, text)
