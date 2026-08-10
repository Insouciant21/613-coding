from __future__ import annotations

import io

import pytest

from coding613.cli.input import InputFormatError, parse_stream_json_input, parse_text_input


def test_text_input_reads_one_prompt_and_rejects_blank() -> None:
    assert parse_text_input(io.StringIO("repair tests\n")) == ("repair tests",)
    with pytest.raises(InputFormatError, match="blank"):
        parse_text_input(io.StringIO(" \n"))


def test_stream_json_input_preserves_order_and_rejects_unknown_type() -> None:
    stream = io.StringIO(
        '{"schema_version":1,"type":"user.message","text":"one"}\n'
        '{"schema_version":1,"type":"user.message","text":"two"}\n'
    )
    assert parse_stream_json_input(stream) == ("one", "two")
    with pytest.raises(InputFormatError, match="unknown event type"):
        parse_stream_json_input(
            io.StringIO('{"schema_version":1,"type":"tool.result","text":"x"}\n')
        )
