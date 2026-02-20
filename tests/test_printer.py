"""Tests for printer module."""

from unittest.mock import patch, MagicMock

from ebay_shipper.printer import print_file


@patch("ebay_shipper.printer.subprocess.run")
def test_print_pdf(mock_run, tmp_path):
    test_file = tmp_path / "test.pdf"
    test_file.write_text("fake pdf content")
    mock_run.return_value = MagicMock(returncode=0, stderr="")

    result = print_file(test_file, "Rollo")

    assert result is True
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "lpr"
    assert "-P" in cmd
    assert "Rollo" in cmd
    assert "media=Custom.4x6in" in cmd[-2]


@patch("ebay_shipper.printer.subprocess.run")
def test_print_zpl(mock_run, tmp_path):
    test_file = tmp_path / "test.zpl"
    test_file.write_text("^XA^XZ")
    mock_run.return_value = MagicMock(returncode=0, stderr="")

    result = print_file(test_file, "Rollo")

    assert result is True
    cmd = mock_run.call_args[0][0]
    assert "raw" in cmd


def test_print_missing_file(tmp_path):
    result = print_file(tmp_path / "nonexistent.pdf", "Rollo")
    assert result is False


@patch("ebay_shipper.printer.subprocess.run")
def test_print_failure(mock_run, tmp_path):
    test_file = tmp_path / "test.pdf"
    test_file.write_text("fake pdf content")
    mock_run.return_value = MagicMock(returncode=1, stderr="printer offline")

    result = print_file(test_file, "Rollo")
    assert result is False
