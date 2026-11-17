import csv
import io
import re


def process_csv_text(csv_text):
    """
    Process CSV text into a list of dictionaries with headers as keys.
    :return: List of row dictionaries or None if invalid
    :rtype: list[dict] or None
    """

    lines = csv_text.strip().split('\n')
    if not lines:
        return None

    # Detect delimiter and header
    sample = '\n'.join(lines[:min(10, len(lines))])

    delimiter = ','
    has_header = False
    try:
        sniffer = csv.Sniffer()
        delimiter = sniffer.sniff(sample).delimiter
        has_header = sniffer.has_header(sample)
    except csv.Error:
        pass

    # Generate headers from first row or create generic ones
    if has_header:
        first_row = next(csv.reader(io.StringIO(lines[0]), delimiter=delimiter))
        headers = [h.strip() if h else f"Column_{i}" for i, h in enumerate(first_row)]
    else:
        first_row = next(csv.reader(io.StringIO(lines[0]), delimiter=delimiter))
        headers = [f"Column_{i}" for i in range(len(first_row))]

    # Parse CSV with safety nets for ragged rows
    reader = csv.DictReader(
        io.StringIO(csv_text),
        delimiter=delimiter,
        fieldnames=headers,
        restkey='_extra_fields',  # Extra columns to be added as extra fields key
        restval=None,  # Missing columns will be added as None
    )

    if has_header:
        next(reader, None)

    return list(reader)


def _clean_text(text):
    """
    Clean up the text content while preserving meaningful structure.

    :param str text: Raw text content to clean
    :returns: Cleaned text content
    :rtype: str
    """
    # Remove NUL characters that can cause PostgreSQL insertion errors
    text = text.replace('\x00', '')
    text = text.replace('\r\n', '\n')

    # Split into lines and process
    lines = text.split('\n')
    result = []
    current_paragraph = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            if current_paragraph:
                result.append(' '.join(current_paragraph))
                current_paragraph = []
            continue

        if stripped.endswith(':') or (len(stripped) < 120 and stripped.endswith('.')):
            if current_paragraph:
                result.append(' '.join(current_paragraph))
                current_paragraph = []
            result.append(stripped)
            continue

        current_paragraph.append(stripped)

    if current_paragraph:
        result.append(' '.join(current_paragraph))

    # Join with single newlines between paragraphs
    text = '\n'.join(result)

    # Clean up extra whitespace
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s+([.,!?;:])', r'\1', text)
    return text.strip()


def chunk_text(text, chunk_size=2000, margin=200, min_chunk_size=1500, max_chunk_size=5000):
    """
    Split text into chunks based on character count with a hard maximum limit.
    The hard max limit is 5000 characters so that the chunks have enough context for the LLM to understand in case of large chunks.

    :param str text: The input text to chunk.
    :param int chunk_size: Target chunk size in characters.
    :param int margin: Allow flexibility in chunk sizes within chunk_size ± margin.
    :param int min_chunk_size: Minimum size a chunk should have before finalizing.
    :param int max_chunk_size: Hard maximum size limit that cannot be exceeded.
    :return: List of text chunks
    :rtype: list[str]
    """
    chunks = []
    current_chunk = []
    current_length = 0

    for para in _clean_text(text).split('\n'):
        para = para.strip()
        if not para:
            continue  # Skip empty lines

        para_length = len(para)

        # If current chunk is too small, try to merge with the next one
        if current_chunk and (current_length + para_length + 1 <= chunk_size + margin):
            current_chunk.append(para)
            current_length += para_length + 1
            continue

        # If the current chunk is large enough, store it
        if current_length >= chunk_size - margin:
            _add_chunk(chunks, " ".join(current_chunk), max_chunk_size)
            current_chunk = [para]  # Start a new chunk
            current_length = para_length
        elif para_length > chunk_size:
            # The paragraph is too big to be merged: store what precedes it and split it by sentences
            if current_chunk:
                _add_chunk(chunks, " ".join(current_chunk), max_chunk_size)
                current_chunk = []
                current_length = 0
            for sentence_chunk in _group_sentences(para, chunk_size):
                _add_chunk(chunks, sentence_chunk, max_chunk_size)
        else:
            current_chunk.append(para)
            current_length += para_length + 1

    # Handle the last chunk
    if current_chunk:
        last_chunk_content = " ".join(current_chunk)
        if chunks and len(last_chunk_content) < min_chunk_size:
            # Try to merge with the previous chunk, but respect max_chunk_size
            if len(chunks[-1]) + len(last_chunk_content) + 1 <= max_chunk_size:
                chunks[-1] += " " + last_chunk_content
            else:
                # Can't merge, add as separate chunk
                _add_chunk(chunks, last_chunk_content, max_chunk_size)
        else:
            _add_chunk(chunks, last_chunk_content, max_chunk_size)

    return chunks


def _add_chunk(chunks, chunk_content, max_chunk_size):
    """Add a chunk, splitting it by words if it exceeds max_chunk_size."""
    if len(chunk_content) <= max_chunk_size:
        chunks.append(chunk_content)
        return
    # Force split oversized chunks by words
    temp_chunk = []
    temp_length = 0
    for word in chunk_content.split():
        word_length = len(word) + 1
        if temp_length + word_length > max_chunk_size:
            if temp_chunk:
                chunks.append(" ".join(temp_chunk))
            temp_chunk = [word]
            temp_length = len(word)
        else:
            temp_chunk.append(word)
            temp_length += word_length
    if temp_chunk:
        chunks.append(" ".join(temp_chunk))


def _group_sentences(para, chunk_size):
    """Group the sentences of a paragraph into texts of at most chunk_size characters."""
    groups = []
    temp_chunk = []
    temp_length = 0
    for sentence in re.split(r'(?<=[.!?])\s+', para):
        sent_length = len(sentence)
        if temp_length + sent_length + 1 > chunk_size:
            if temp_chunk:
                groups.append(" ".join(temp_chunk))
            temp_chunk = [sentence]
            temp_length = sent_length
        else:
            temp_chunk.append(sentence)
            temp_length += sent_length + 1
    if temp_chunk:
        groups.append(" ".join(temp_chunk))
    return groups
