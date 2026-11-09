from __future__ import annotations

import json
import stat
import zipfile
from pathlib import Path

import pytest

import backtest_auditor.implementation_risk.adapters.engine_export as export_module
from backtest_auditor.implementation_risk import (
    ENGINE_EXPORT_ENVELOPE_FILE,
    EngineAdapterError,
    EngineAdapterErrorCode,
    EngineExportFileBundleAdapter,
    EngineExportPayload,
    EngineExportReader,
    SupportedEngine,
    VerifiedEngineExport,
    engine_export_envelope_from_json,
    engine_export_envelope_to_json,
)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def _manifest(directory: Path) -> dict:
    return json.loads((directory / ENGINE_EXPORT_ENVELOPE_FILE).read_text())


def _write_manifest(directory: Path, value: dict) -> None:
    (directory / ENGINE_EXPORT_ENVELOPE_FILE).write_bytes(_json_bytes(value))


def test_engine_export_adapter_implements_reader_port() -> None:
    assert isinstance(EngineExportFileBundleAdapter(), EngineExportReader)


def test_directory_and_zip_round_trip_preserve_verified_bytes(
    tmp_path: Path,
    verified_engine_export: VerifiedEngineExport,
) -> None:
    adapter = EngineExportFileBundleAdapter()
    directory = adapter.write(verified_engine_export, tmp_path / "export")
    archive = adapter.write(verified_engine_export, tmp_path / "export.zip")

    assert adapter.read(directory) == verified_engine_export
    assert adapter.read(archive) == verified_engine_export
    assert _manifest(directory) == engine_export_envelope_to_json(
        verified_engine_export.envelope
    )


def test_writer_supports_nested_payload_paths(tmp_path: Path) -> None:
    export = VerifiedEngineExport.create(
        run_id="nested",
        engine=SupportedEngine.BT,
        engine_version=None,
        export_format_id="backtest-auditor.bt",
        export_format_version="1.0",
        declared_levels=(),
        payloads=(
            EngineExportPayload(
                "tables/metadata.csv",
                "metadata",
                "text/csv",
                b"name,value\nengine,bt\n",
            ),
        ),
    )
    adapter = EngineExportFileBundleAdapter()
    directory = adapter.write(export, tmp_path / "nested")
    archive = adapter.write(export, tmp_path / "nested.zip")

    assert (directory / "tables" / "metadata.csv").is_file()
    assert adapter.read(directory) == export
    assert adapter.read(archive) == export


def test_zip_output_is_byte_deterministic_and_safe_metadata(
    tmp_path: Path,
    verified_engine_export: VerifiedEngineExport,
) -> None:
    adapter = EngineExportFileBundleAdapter()
    first = adapter.write(verified_engine_export, tmp_path / "first.zip")
    second = adapter.write(verified_engine_export, tmp_path / "second.zip")

    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        infos = archive.infolist()
        assert infos[0].filename == ENGINE_EXPORT_ENVELOPE_FILE
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in infos)
        assert all(stat.S_ISREG(info.external_attr >> 16) for info in infos)


def test_envelope_json_round_trip_is_exact(
    verified_engine_export: VerifiedEngineExport,
) -> None:
    encoded = engine_export_envelope_to_json(verified_engine_export.envelope)
    assert engine_export_envelope_from_json(encoded) == verified_engine_export.envelope


def test_writer_requires_explicit_overwrite_and_replaces_atomically(
    tmp_path: Path,
    verified_engine_export: VerifiedEngineExport,
) -> None:
    adapter = EngineExportFileBundleAdapter()
    for destination in (tmp_path / "export", tmp_path / "export.zip"):
        adapter.write(verified_engine_export, destination)
        with pytest.raises(EngineAdapterError) as captured:
            adapter.write(verified_engine_export, destination)
        assert captured.value.code is EngineAdapterErrorCode.WRITE_FAILED
        assert (
            adapter.write(
                verified_engine_export,
                destination,
                overwrite=True,
            )
            == destination
        )
        assert adapter.read(destination) == verified_engine_export


@pytest.mark.parametrize("name", ["export.json", "export.tar", "export.csv"])
def test_writer_rejects_unsupported_destination_suffix(
    tmp_path: Path,
    verified_engine_export: VerifiedEngineExport,
    name: str,
) -> None:
    with pytest.raises(EngineAdapterError) as captured:
        EngineExportFileBundleAdapter().write(
            verified_engine_export,
            tmp_path / name,
        )
    assert captured.value.code is EngineAdapterErrorCode.SOURCE_TYPE_UNSUPPORTED


def test_writer_rejects_invalid_export_value(tmp_path: Path) -> None:
    with pytest.raises(EngineAdapterError) as captured:
        EngineExportFileBundleAdapter().write(
            "invalid",  # type: ignore[arg-type]
            tmp_path / "export",
        )
    assert captured.value.code is EngineAdapterErrorCode.OUTPUT_CONTRACT_VIOLATION


def test_reader_rejects_missing_unsupported_and_symlink_sources(
    tmp_path: Path,
) -> None:
    adapter = EngineExportFileBundleAdapter()
    with pytest.raises(EngineAdapterError) as missing:
        adapter.read(tmp_path / "missing")
    assert missing.value.code is EngineAdapterErrorCode.SOURCE_NOT_FOUND

    text = tmp_path / "export.txt"
    text.write_text("not an export")
    with pytest.raises(EngineAdapterError) as unsupported:
        adapter.read(text)
    assert unsupported.value.code is EngineAdapterErrorCode.SOURCE_TYPE_UNSUPPORTED

    symlink = tmp_path / "link"
    symlink.symlink_to(text)
    with pytest.raises(EngineAdapterError) as linked:
        adapter.read(symlink)
    assert linked.value.code is EngineAdapterErrorCode.SOURCE_TYPE_UNSUPPORTED


def test_reader_rejects_missing_envelope_and_extra_or_missing_payloads(
    tmp_path: Path,
    verified_engine_export: VerifiedEngineExport,
) -> None:
    adapter = EngineExportFileBundleAdapter()
    missing_envelope = tmp_path / "missing-envelope"
    missing_envelope.mkdir()
    (missing_envelope / "returns.csv").write_text("x")
    with pytest.raises(EngineAdapterError) as captured:
        adapter.read(missing_envelope)
    assert captured.value.code is EngineAdapterErrorCode.MISSING_ENVELOPE

    missing_payload = adapter.write(verified_engine_export, tmp_path / "missing")
    (missing_payload / "returns.csv").unlink()
    with pytest.raises(EngineAdapterError) as captured:
        adapter.read(missing_payload)
    assert captured.value.code is EngineAdapterErrorCode.MISSING_FILE

    extra_payload = adapter.write(verified_engine_export, tmp_path / "extra")
    (extra_payload / "extra.csv").write_text("x")
    with pytest.raises(EngineAdapterError) as captured:
        adapter.read(extra_payload)
    assert captured.value.code is EngineAdapterErrorCode.UNDECLARED_FILE


def test_reader_detects_size_and_hash_tampering(
    tmp_path: Path,
    verified_engine_export: VerifiedEngineExport,
) -> None:
    adapter = EngineExportFileBundleAdapter()
    size_export = adapter.write(verified_engine_export, tmp_path / "size")
    (size_export / "returns.csv").write_bytes(b"changed-size")
    with pytest.raises(EngineAdapterError) as captured:
        adapter.read(size_export)
    assert captured.value.code is EngineAdapterErrorCode.SIZE_MISMATCH

    hash_export = adapter.write(verified_engine_export, tmp_path / "hash")
    original = (hash_export / "returns.csv").read_bytes()
    changed = bytes([original[0] ^ 1]) + original[1:]
    (hash_export / "returns.csv").write_bytes(changed)
    with pytest.raises(EngineAdapterError) as captured:
        adapter.read(hash_export)
    assert captured.value.code is EngineAdapterErrorCode.HASH_MISMATCH


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (
            lambda value: value.update(envelope_schema_version="9.0"),
            EngineAdapterErrorCode.UNSUPPORTED_ENVELOPE_VERSION,
        ),
        (
            lambda value: value.update(unexpected=True),
            EngineAdapterErrorCode.INVALID_ENVELOPE,
        ),
        (
            lambda value: value.update(engine="unknown"),
            EngineAdapterErrorCode.INVALID_ENVELOPE,
        ),
        (
            lambda value: value.update(declared_levels=["unknown"]),
            EngineAdapterErrorCode.INVALID_ENVELOPE,
        ),
        (
            lambda value: value.update(source_sha256="0" * 64),
            EngineAdapterErrorCode.INVALID_ENVELOPE,
        ),
    ],
)
def test_reader_rejects_invalid_envelope_semantics(
    tmp_path: Path,
    verified_engine_export: VerifiedEngineExport,
    mutator,
    code: EngineAdapterErrorCode,
) -> None:
    directory = EngineExportFileBundleAdapter().write(
        verified_engine_export,
        tmp_path / code.value,
    )
    value = _manifest(directory)
    mutator(value)
    _write_manifest(directory, value)
    with pytest.raises(EngineAdapterError) as captured:
        EngineExportFileBundleAdapter().read(directory)
    assert captured.value.code is code


@pytest.mark.parametrize(
    "data",
    [
        b"not json",
        b'{"engine":"vectorbt","engine":"bt"}\n',
        b'{"value":NaN}\n',
        b'{"value": 1}\n',
        "{}\n".encode("utf-16"),
    ],
)
def test_reader_rejects_malformed_or_noncanonical_json(
    tmp_path: Path,
    data: bytes,
) -> None:
    directory = tmp_path / str(abs(hash(data)))
    directory.mkdir()
    (directory / ENGINE_EXPORT_ENVELOPE_FILE).write_bytes(data)
    with pytest.raises(EngineAdapterError) as captured:
        EngineExportFileBundleAdapter().read(directory)
    assert captured.value.code is EngineAdapterErrorCode.INVALID_JSON


@pytest.mark.parametrize("name", ["../escape", "/absolute", "nested\\bad"])
def test_reader_rejects_unsafe_zip_paths(tmp_path: Path, name: str) -> None:
    archive = tmp_path / (str(abs(hash(name))) + ".zip")
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr(name, b"x")
    with pytest.raises(EngineAdapterError) as captured:
        EngineExportFileBundleAdapter().read(archive)
    assert captured.value.code is EngineAdapterErrorCode.UNSAFE_ARCHIVE


def test_reader_rejects_duplicate_and_encrypted_or_symlink_zip_entries(
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(duplicate, "w") as stream:
        stream.writestr("same.csv", b"a")
        with pytest.warns(UserWarning, match="Duplicate name"):
            stream.writestr("same.csv", b"b")
    with pytest.raises(EngineAdapterError) as captured:
        EngineExportFileBundleAdapter().read(duplicate)
    assert captured.value.code is EngineAdapterErrorCode.UNSAFE_ARCHIVE

    symlink = tmp_path / "symlink.zip"
    with zipfile.ZipFile(symlink, "w") as stream:
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        stream.writestr(info, b"target")
    with pytest.raises(EngineAdapterError) as captured:
        EngineExportFileBundleAdapter().read(symlink)
    assert captured.value.code is EngineAdapterErrorCode.UNSAFE_ARCHIVE


def test_resource_limits_are_enforced_without_large_allocations(
    tmp_path: Path,
    verified_engine_export: VerifiedEngineExport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(export_module, "_MAX_FILES", 0)
    directory = tmp_path / "too-many"
    directory.mkdir()
    (directory / ENGINE_EXPORT_ENVELOPE_FILE).write_text("{}\n")
    (directory / "payload.csv").write_text("x")
    with pytest.raises(EngineAdapterError) as captured:
        EngineExportFileBundleAdapter().read(directory)
    assert captured.value.code is EngineAdapterErrorCode.RESOURCE_LIMIT_EXCEEDED

    monkeypatch.setattr(export_module, "_MAX_FILES", 64)
    monkeypatch.setattr(export_module, "_MAX_FILE_BYTES", 1)
    written = tmp_path / "oversized"
    written.mkdir()
    for payload in verified_engine_export.payloads:
        (written / payload.path).write_bytes(payload.data)
    (written / ENGINE_EXPORT_ENVELOPE_FILE).write_bytes(
        _json_bytes(engine_export_envelope_to_json(verified_engine_export.envelope))
    )
    with pytest.raises(EngineAdapterError) as captured:
        EngineExportFileBundleAdapter().read(written)
    assert captured.value.code is EngineAdapterErrorCode.RESOURCE_LIMIT_EXCEEDED


def test_directory_rejects_payload_symlink(
    tmp_path: Path,
    verified_engine_export: VerifiedEngineExport,
) -> None:
    external = tmp_path / "outside.csv"
    external.write_text("outside")
    directory = EngineExportFileBundleAdapter().write(
        verified_engine_export,
        tmp_path / "export",
    )
    (directory / "returns.csv").unlink()
    (directory / "returns.csv").symlink_to(external)
    with pytest.raises(EngineAdapterError) as captured:
        EngineExportFileBundleAdapter().read(directory)
    assert captured.value.code is EngineAdapterErrorCode.SOURCE_TYPE_UNSUPPORTED


def test_write_failure_rolls_back_existing_directory(
    tmp_path: Path,
    verified_engine_export: VerifiedEngineExport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = EngineExportFileBundleAdapter()
    destination = adapter.write(verified_engine_export, tmp_path / "export")
    original = (destination / ENGINE_EXPORT_ENVELOPE_FILE).read_bytes()

    def fail(*_args, **_kwargs):
        raise OSError("simulated failure")

    monkeypatch.setattr(export_module, "_write_directory", fail)
    with pytest.raises(EngineAdapterError) as captured:
        adapter.write(verified_engine_export, destination, overwrite=True)
    assert captured.value.code is EngineAdapterErrorCode.WRITE_FAILED
    assert (destination / ENGINE_EXPORT_ENVELOPE_FILE).read_bytes() == original


def test_engine_adapter_error_string_contains_stable_context() -> None:
    error = EngineAdapterError(
        EngineAdapterErrorCode.MAPPING_FAILED,
        "could not map row",
        engine=SupportedEngine.BACKTRADER,
        adapter_id="backtest-auditor.backtrader",
        engine_error_code="backtrader.bad_row",
        file_path="orders.csv",
        row_number=3,
        field="size",
    )
    assert str(error) == (
        "mapping_failed: could not map row "
        "(engine=backtrader, adapter=backtest-auditor.backtrader, "
        "engine_error=backtrader.bad_row, file=orders.csv, row=3, field=size)"
    )


def test_writer_rejects_existing_wrong_destination_types(
    tmp_path: Path,
    verified_engine_export: VerifiedEngineExport,
) -> None:
    zip_directory = tmp_path / "wrong.zip"
    zip_directory.mkdir()
    with pytest.raises(EngineAdapterError) as captured:
        EngineExportFileBundleAdapter().write(
            verified_engine_export,
            zip_directory,
            overwrite=True,
        )
    assert captured.value.code is EngineAdapterErrorCode.WRITE_FAILED

    file_destination = tmp_path / "directory"
    file_destination.write_text("file")
    with pytest.raises(EngineAdapterError) as captured:
        EngineExportFileBundleAdapter().write(
            verified_engine_export,
            file_destination,
            overwrite=True,
        )
    assert captured.value.code is EngineAdapterErrorCode.WRITE_FAILED
