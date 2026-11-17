"""Export of the translations of the modules and of the records, to the translation file formats."""

from __future__ import annotations

from .files import TranslationFileWriter

from .readers import TranslationModuleReader, TranslationRecordReader

def trans_export(lang, modules, buffer, format, env):
    reader = TranslationModuleReader(env.cr, modules=modules, lang=lang)
    if not reader:
        return False
    writer = TranslationFileWriter(buffer, fileformat=format, lang=lang)
    writer.write_rows(reader)
    return True


def trans_export_records(lang, model_name, ids, buffer, format, env):
    reader = TranslationRecordReader(env.cr, model_name, ids, lang=lang)
    if not reader:
        return False
    writer = TranslationFileWriter(buffer, fileformat=format, lang=lang)
    writer.write_rows(reader)
    return True
