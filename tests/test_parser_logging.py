"""Parser logging keeps debug details in the UTF-8 log and info on console."""

import logging

from build.lib.parser_logging import configure_logging


def test_parser_logging_keeps_debug_file_and_info_console(tmp_path, monkeypatch):
    configured = {}
    monkeypatch.setattr(logging, 'basicConfig', lambda **kwargs: configured.update(kwargs))
    log = tmp_path / 'parser.log'
    configure_logging(LOG_FILE=log)
    file_handler, console_handler = configured['handlers']
    try:
        assert configured['level'] == logging.DEBUG
        assert file_handler.level == logging.DEBUG
        assert console_handler.level == logging.INFO
        file_handler.emit(logging.LogRecord('parser', logging.DEBUG, '', 0, 'Source: caf\u00e9', (), None))
        file_handler.flush()
        assert log.read_text(encoding='utf-8') == 'Source: caf\u00e9\n'
    finally:
        file_handler.close()
        console_handler.close()
