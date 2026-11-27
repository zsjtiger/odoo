"""The PO files of the translations: their paths and the translations they contain."""

from __future__ import annotations

import polib
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from contextlib import suppress
from os.path import join
from odoo.tools.misc import file_open, file_path

from .languages import get_base_langs

def get_po_paths(module_name: str, lang: str) -> Iterator[str]:
    po_paths = (
        join(module_name, dir_, filename + '.po')
        for filename in get_base_langs(lang)
        for dir_ in ('i18n', 'i18n_extra')
    )
    for path in po_paths:
        with suppress(FileNotFoundError):
            yield file_path(path)


def get_datafile_translation_path(module_name: str) -> Iterator[str]:
    from odoo.modules import Manifest  # noqa: PLC0415
    # if we are importing a module, we have an env, hide warnings
    manifest = Manifest.for_addon(module_name, display_warning=False) or {}
    for data_type in ('data', 'demo'):
        for path in manifest.get(data_type, ()):
            if path.endswith(('.xml', '.csv')):
                yield file_path(join(module_name, path))


CHARSET_REGEX = re.compile(rb'Content-Type:[^\n]+charset=([\w_\-:\.]+)')


def get_translations_for_references(po_path: str, references: Iterable[str]) -> dict[str, dict[str, str]]:
    """A faster extractor of translations for the given references from a PO file.

    The references should be location strings to look for in PO entries (comments starting with ``#:``).

    We use a single-pass approach to read the file in binary mode, locate the relevant entries,
    and parse only these entries in one go with ``polib``.

    Since we parse the file manually, we have two requirements:
    1. The PO file should be well-formed (valid after ``msgcat file.po``).
    2. Each entry must be separated by at least two consecutive newlines.

    :param str po_path: Path to the PO file.
    :param Iterable[str] references: List of reference strings to look for.
    :return: Dictionary mapping references to a dictionary mapping msgid to msgstr.
    """
    normalized_references = {ref.strip() for ref in references if ref and ref.strip()}
    if not normalized_references:
        return {}

    try:
        with file_open(po_path, 'rb') as po_file:
            data = po_file.read()
    except FileNotFoundError:
        return {}

    if not data:
        return {}

    # Normalize line endings to LF for consistent processing.
    data = data.replace(b'\r\n', b'\n')

    data_find = data.find
    data_rfind = data.rfind
    data_len = len(data)

    double_newline = b'\n\n'
    double_newline_len = 2

    # Find the header entry and extract the encoding if present.
    #
    #                        [top of file comments]
    # (header_start_pos) --> msgid ""[\n]
    #                        msgstr ""[\n]
    #                        "Content-Type: text/plain; charset=UTF-8\n"[\n]
    #                        "X-key: value"[\n] <-- (header_end_pos)
    #                        [\n]
    #                        [first entry][\n]

    header_start_pos = data_find(b'msgid ""\nmsgstr ""')
    if header_start_pos == -1:
        return {}

    header_end_pos = data_find(double_newline, header_start_pos)
    if header_end_pos == -1:
        return {}

    header_bytes = data[0: header_end_pos]
    match = CHARSET_REGEX.search(header_bytes)
    encoding = match.group(1).decode('ascii') if match else 'utf-8'

    # Store the entries to concatenate later. The first entry is the header.
    entries = [header_bytes]

    encoded_references = {ref.encode(encoding, errors='ignore') for ref in normalized_references}
    matched_entry_positions = set()
    nl_hash_colon = b'\n#:'
    nl_hash_colon_len = 3
    search_start_pos = header_end_pos

    while True:
        search_start_pos = data_find(nl_hash_colon, search_start_pos)
        if search_start_pos == -1:
            break

        line_end_pos = data_find(b'\n', search_start_pos + nl_hash_colon_len)
        if line_end_pos == -1:
            line_end_pos = data_len

        line_bytes = data[search_start_pos + nl_hash_colon_len: line_end_pos]
        refs_on_line = set(line_bytes.split())

        if not encoded_references.isdisjoint(refs_on_line):
            # We found a line with at least one reference we need. Find the entry boundaries:
            #
            #                       [previous entry][\n]
            #                       [\n]
            # (entry_start_pos) --> #. base[\n] <-- (full_reference_start)
            #                       #: reference1 reference2[\n]
            #                       msgid "source"[\n]
            #                       msgstr ""[\n]
            #                       "line1\n"[\n]
            #                       "line2\n"[\n] <-- (entry_end_pos)
            #                       [\n]
            #                       [next entry]

            entry_start_pos = data_rfind(double_newline, header_end_pos, search_start_pos)
            if entry_start_pos == -1:
                entry_start_pos = header_end_pos
            else:
                entry_start_pos += double_newline_len

            if entry_start_pos not in matched_entry_positions:
                # This entry has not been added to `entries` yet, so we add it now.
                matched_entry_positions.add(entry_start_pos)

                entry_end_pos = data_find(double_newline, search_start_pos)
                if entry_end_pos == -1:
                    entry_end_pos = data_len

                entries.append(data[entry_start_pos:entry_end_pos])

                search_start_pos = entry_end_pos
                continue

        search_start_pos = line_end_pos

    if len(entries) == 1:
        return {}

    # Parse all entries in a single polib call.
    filtered_po = polib.pofile(double_newline.join(entries).decode(encoding), encoding=encoding)

    translations = defaultdict(dict)

    for entry in filtered_po:
        for occ in entry.occurrences:
            occ_str = f'{occ[0]}:{occ[1]}' if occ[1] else occ[0]
            if occ_str in normalized_references and entry.msgstr and entry.msgid:
                translations[occ_str][entry.msgid] = entry.msgstr

    return dict(translations)
