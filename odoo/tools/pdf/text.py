"""The text of the PDF files: the reshaping of the right-to-left text."""

from __future__ import annotations

import unicodedata
from odoo.tools.arabic_reshaper import reshape


def reshape_text(text):
    """
    Display the text based on his first character unicode name to choose Right-to-left or Left-to-right
    This is just a hotfix to make things work
    In the future the clean way be to use arabic-reshaper and python3-bidi libraries


    Here we want to check the text is in a right-to-left language and if then, flip before returning it.
    Depending on the language, the type should be Left-to-Right, Right-to-Left, or Right-to-Left Arabic
    (Refer to this https://www.unicode.org/reports/tr9/#Bidirectional_Character_Types)
    The base module ```unicodedata``` with his function ```bidirectional(str)``` helps us by taking a character in
    argument and returns his type:
    - 'L' for Left-to-Right character
    - 'R' or 'AL' for Right-to-Left character

    So we have to check if the first character of the text is of type 'R' or 'AL', and check that there is no
    character in the rest of the text that is of type 'L'. Based on that we can confirm we have a fully Right-to-Left language,
    then we can flip the text before returning it.
    """
    if not text:
        return ''
    maybe_rtl_letter = text.lstrip()[:1] or ' '
    maybe_ltr_text = text[1:]
    first_letter_is_rtl = unicodedata.bidirectional(maybe_rtl_letter) in ('AL', 'R')
    no_letter_is_ltr = not any(unicodedata.bidirectional(letter) == 'L' for letter in maybe_ltr_text)
    if first_letter_is_rtl and no_letter_is_ltr:
        text = reshape(text)
        text = text[::-1]

    return text
