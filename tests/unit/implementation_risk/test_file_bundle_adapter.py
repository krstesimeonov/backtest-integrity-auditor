from __future__ import annotations

import hashlib
import json
import os
import stat
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

import backtest_auditor.implementation_risk.adapters.canonical_bundle as bundle_module
from backtest_auditor.implementation_risk import (
    CanonicalRunArtifacts,
    CashArtifacts,
    CashBalance,
    CanonicalArtifactBundleReader,
    CanonicalArtifactBundleWriter,
    EngineRunReference,
)
from backtest_auditor.implementation_risk.adapters.canonical_bundle import (
    BUNDLE_SCHEMA_VERSION,
    MANIFEST_FILE,
    CanonicalArtifactFileBundleAdapter,
)
from backtest_auditor.implementation_risk.adapters.errors import (
    BundleContractError,
    BundleErrorCode,
)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def _content_identity(manifest: dict) -> str:
    body = dict(manifest)
    del body["bundle_content_sha256"]
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _read_manifest(directory: Path) -> dict:
    return json.loads((directory / MANIFEST_FILE).read_text())


def _write_manifest(directory: Path, manifest: dict) -> None:
    manifest["bundle_content_sha256"] = _content_identity(manifest)
    (directory / MANIFEST_FILE).write_bytes(_json_bytes(manifest))


def _replace_payload(
    directory: Path,
    file_name: str,
    data: bytes,
    *,
    record_count: int | None = None,
) -> None:
    (directory / file_name).write_bytes(data)
    manifest = _read_manifest(directory)
    entry = next(item for item in manifest["files"] if item["path"] == file_name)
    entry["size_bytes"] = len(data)
    entry["sha256"] = hashlib.sha256(data).hexdigest()
    if record_count is not None:
        entry["record_count"] = record_count
    _write_manifest(directory, manifest)


def test_directory_round_trip_writes_human_readable_hybrid_contract(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    adapter = CanonicalArtifactFileBundleAdapter()
    destination = tmp_path / "bundle"

    result = adapter.write(canonical_file_bundle, destination)

    assert result == destination
    assert adapter.read(destination) == canonical_file_bundle
    manifest = _read_manifest(destination)
    assert manifest["bundle_schema_version"] == BUNDLE_SCHEMA_VERSION
    assert manifest["levels"]["trade"] == {
        "status": "available",
        "files": ["trade_fills.csv", "trades.csv"],
    }
    assert manifest["levels"]["cash"] == {
        "status": "available",
        "files": ["cash_balances.csv", "cash_movements.csv"],
    }
    assert (destination / "specification.json").read_text().startswith("{\n")
    assert (
        (destination / "fills.csv").read_text().splitlines()[1].endswith(",taker,XNAS")
    )
    assert (destination / "trade_fills.csv").read_text().splitlines()[1] == (
        "trade-1,fill-1"
    )


def test_file_adapter_implements_engine_neutral_reader_and_writer_ports() -> None:
    adapter = CanonicalArtifactFileBundleAdapter()

    assert isinstance(adapter, CanonicalArtifactBundleReader)
    assert isinstance(adapter, CanonicalArtifactBundleWriter)


def test_zip_writer_is_byte_deterministic_and_round_trips(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    adapter = CanonicalArtifactFileBundleAdapter()
    first = adapter.write(canonical_file_bundle, tmp_path / "first.zip")
    second = adapter.write(canonical_file_bundle, tmp_path / "second.zip")

    assert first.read_bytes() == second.read_bytes()
    assert adapter.read(first) == canonical_file_bundle
    with zipfile.ZipFile(first) as archive:
        infos = archive.infolist()
        assert infos[0].filename == MANIFEST_FILE
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in infos)
        assert all(stat.S_ISREG(info.external_attr >> 16) for info in infos)


def test_header_only_csv_preserves_available_empty_vs_unavailable(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    run = canonical_file_bundle.run
    timestamp = canonical_file_bundle.equity[0].timestamp  # type: ignore[index]
    bundle = CanonicalRunArtifacts(
        run=run,
        signals=(),
        orders=None,
        cash=CashArtifacts(
            balances=(CashBalance(timestamp, "USD", 0),),
            movements=None,
        ),
    )
    destination = CanonicalArtifactFileBundleAdapter().write(
        bundle,
        tmp_path / "bundle",
    )

    restored = CanonicalArtifactFileBundleAdapter().read(destination)
    manifest = _read_manifest(destination)
    assert restored == bundle
    assert (destination / "signals.csv").read_text().count("\n") == 1
    assert not (destination / "orders.csv").exists()
    assert not (destination / "cash_movements.csv").exists()
    assert manifest["levels"]["signal"]["status"] == "available"
    assert manifest["levels"]["order"]["status"] == "unavailable"


def test_unknown_engine_version_round_trips_without_inference(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    run = EngineRunReference(
        canonical_file_bundle.run.run_id,
        canonical_file_bundle.run.engine_name,
        None,
        canonical_file_bundle.run.source_sha256,
    )
    bundle = CanonicalRunArtifacts(run=run, returns=())
    destination = CanonicalArtifactFileBundleAdapter().write(
        bundle,
        tmp_path / "bundle",
    )

    assert CanonicalArtifactFileBundleAdapter().read(destination) == bundle
    assert _read_manifest(destination)["run"]["engine_version"] is None


def test_writer_requires_explicit_overwrite_and_supports_it_atomically(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    adapter = CanonicalArtifactFileBundleAdapter()
    directory = adapter.write(canonical_file_bundle, tmp_path / "bundle")
    archive = adapter.write(canonical_file_bundle, tmp_path / "bundle.zip")

    for destination in (directory, archive):
        with pytest.raises(BundleContractError) as captured:
            adapter.write(canonical_file_bundle, destination)
        assert captured.value.code is BundleErrorCode.DESTINATION_EXISTS
        assert (
            adapter.write(
                canonical_file_bundle,
                destination,
                overwrite=True,
            )
            == destination
        )
        assert adapter.read(destination) == canonical_file_bundle


@pytest.mark.parametrize("name", ["bundle.json", "bundle.tar"])
def test_writer_rejects_unsupported_destination_suffix(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
    name: str,
) -> None:
    with pytest.raises(BundleContractError) as captured:
        CanonicalArtifactFileBundleAdapter().write(
            canonical_file_bundle,
            tmp_path / name,
        )
    assert captured.value.code is BundleErrorCode.DESTINATION_TYPE_UNSUPPORTED


def test_writer_rejects_noncanonical_bundle(tmp_path: Path) -> None:
    with pytest.raises(BundleContractError) as captured:
        CanonicalArtifactFileBundleAdapter().write(
            "bundle",  # type: ignore[arg-type]
            tmp_path / "bundle",
        )
    assert captured.value.code is BundleErrorCode.DOMAIN_VALIDATION_FAILED


def test_reader_rejects_missing_or_unsupported_source(tmp_path: Path) -> None:
    adapter = CanonicalArtifactFileBundleAdapter()
    with pytest.raises(BundleContractError) as missing:
        adapter.read(tmp_path / "missing")
    assert missing.value.code is BundleErrorCode.SOURCE_NOT_FOUND

    source = tmp_path / "bundle.txt"
    source.write_text("not a bundle")
    with pytest.raises(BundleContractError) as unsupported:
        adapter.read(source)
    assert unsupported.value.code is BundleErrorCode.SOURCE_TYPE_UNSUPPORTED


def test_reader_rejects_missing_extra_or_changed_files(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    adapter = CanonicalArtifactFileBundleAdapter()

    missing_manifest = adapter.write(canonical_file_bundle, tmp_path / "missing")
    (missing_manifest / MANIFEST_FILE).unlink()
    with pytest.raises(BundleContractError) as captured:
        adapter.read(missing_manifest)
    assert captured.value.code is BundleErrorCode.MISSING_MANIFEST

    extra = adapter.write(canonical_file_bundle, tmp_path / "extra")
    (extra / "extra.csv").write_text("x\n")
    with pytest.raises(BundleContractError) as captured:
        adapter.read(extra)
    assert captured.value.code is BundleErrorCode.UNDECLARED_FILE

    missing_file = adapter.write(canonical_file_bundle, tmp_path / "missing-file")
    (missing_file / "fills.csv").unlink()
    with pytest.raises(BundleContractError) as captured:
        adapter.read(missing_file)
    assert captured.value.code is BundleErrorCode.MISSING_FILE

    changed = adapter.write(canonical_file_bundle, tmp_path / "changed")
    with (changed / "fills.csv").open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(BundleContractError) as captured:
        adapter.read(changed)
    assert captured.value.code is BundleErrorCode.SIZE_MISMATCH


def test_reader_detects_hash_and_record_count_mismatches(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    adapter = CanonicalArtifactFileBundleAdapter()
    hash_bundle = adapter.write(canonical_file_bundle, tmp_path / "hash")
    manifest = _read_manifest(hash_bundle)
    entry = next(item for item in manifest["files"] if item["path"] == "fills.csv")
    entry["sha256"] = "0" * 64
    _write_manifest(hash_bundle, manifest)
    with pytest.raises(BundleContractError) as captured:
        adapter.read(hash_bundle)
    assert captured.value.code is BundleErrorCode.HASH_MISMATCH

    count_bundle = adapter.write(canonical_file_bundle, tmp_path / "count")
    manifest = _read_manifest(count_bundle)
    entry = next(item for item in manifest["files"] if item["path"] == "fills.csv")
    entry["record_count"] = 2
    _write_manifest(count_bundle, manifest)
    with pytest.raises(BundleContractError) as captured:
        adapter.read(count_bundle)
    assert captured.value.code is BundleErrorCode.RECORD_COUNT_MISMATCH


def test_reader_rejects_domain_contradictions_after_file_integrity_passes(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    directory = CanonicalArtifactFileBundleAdapter().write(
        canonical_file_bundle,
        tmp_path / "bundle",
    )
    fills = (directory / "fills.csv").read_text()
    _replace_payload(
        directory,
        "fills.csv",
        fills.replace(",10,100.25,", ",5,100.25,").encode(),
    )

    with pytest.raises(BundleContractError) as captured:
        CanonicalArtifactFileBundleAdapter().read(directory)

    assert captured.value.code is BundleErrorCode.DOMAIN_VALIDATION_FAILED
    assert "completely filled" in str(captured.value)


def test_reader_rejects_duplicate_cash_identity_after_row_validation(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    directory = CanonicalArtifactFileBundleAdapter().write(
        canonical_file_bundle,
        tmp_path / "bundle",
    )
    data = (directory / "cash_balances.csv").read_bytes()
    header, row = data.splitlines()
    duplicate = b"\n".join((header, row, row, b""))
    _replace_payload(
        directory,
        "cash_balances.csv",
        duplicate,
        record_count=2,
    )

    with pytest.raises(BundleContractError) as captured:
        CanonicalArtifactFileBundleAdapter().read(directory)

    assert captured.value.code is BundleErrorCode.DOMAIN_VALIDATION_FAILED
    assert "unique" in str(captured.value)


def test_reader_rejects_manifest_values_that_normalize_silently(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    directory = CanonicalArtifactFileBundleAdapter().write(
        canonical_file_bundle,
        tmp_path / "bundle",
    )
    manifest = _read_manifest(directory)
    manifest["run"]["engine_name"] = " engine "
    _write_manifest(directory, manifest)

    with pytest.raises(BundleContractError) as captured:
        CanonicalArtifactFileBundleAdapter().read(directory)

    assert captured.value.code is BundleErrorCode.DOMAIN_VALIDATION_FAILED
    assert "round-trip" in str(captured.value)


def test_reader_rejects_invalid_bundle_identity(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    directory = CanonicalArtifactFileBundleAdapter().write(
        canonical_file_bundle,
        tmp_path / "bundle",
    )
    manifest = _read_manifest(directory)
    manifest["bundle_content_sha256"] = "0" * 64
    (directory / MANIFEST_FILE).write_bytes(_json_bytes(manifest))

    with pytest.raises(BundleContractError) as captured:
        CanonicalArtifactFileBundleAdapter().read(directory)

    assert captured.value.code is BundleErrorCode.HASH_MISMATCH


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda value: value.update(extra=True),
            BundleErrorCode.INVALID_MANIFEST,
        ),
        (
            lambda value: value.update(bundle_schema_version=1),
            BundleErrorCode.INVALID_MANIFEST,
        ),
        (
            lambda value: value["run"].update(source_sha256="bad"),
            BundleErrorCode.INVALID_MANIFEST,
        ),
        (
            lambda value: value["levels"].pop("return"),
            BundleErrorCode.INVALID_MANIFEST,
        ),
        (
            lambda value: value["levels"]["return"].update(status="unknown"),
            BundleErrorCode.INVALID_MANIFEST,
        ),
        (
            lambda value: value["levels"]["return"].update(files="returns.csv"),
            BundleErrorCode.INVALID_MANIFEST,
        ),
        (
            lambda value: value["levels"]["trade"]["files"].reverse(),
            BundleErrorCode.INVALID_MANIFEST,
        ),
        (
            lambda value: value["levels"]["return"].update(files=["orders.csv"]),
            BundleErrorCode.INVALID_MANIFEST,
        ),
        (
            lambda value: value["levels"]["return"].update(status="unavailable"),
            BundleErrorCode.INVALID_MANIFEST,
        ),
        (
            lambda value: value["levels"]["cash"].update(files=[]),
            BundleErrorCode.INVALID_MANIFEST,
        ),
        (
            lambda value: value["levels"]["return"].update(files=[]),
            BundleErrorCode.INVALID_MANIFEST,
        ),
        (
            lambda value: value["files"][0].update(path="unknown.csv"),
            BundleErrorCode.INVALID_MANIFEST,
        ),
        (
            lambda value: value["files"][0].update(media_type="text/plain"),
            BundleErrorCode.INVALID_MANIFEST,
        ),
        (
            lambda value: value["files"][0].update(size_bytes=-1),
            BundleErrorCode.INVALID_MANIFEST,
        ),
        (
            lambda value: value["files"][0].update(size_bytes=600_000_000),
            BundleErrorCode.RESOURCE_LIMIT_EXCEEDED,
        ),
        (
            lambda value: value["files"][0].update(record_count=-1),
            BundleErrorCode.INVALID_MANIFEST,
        ),
        (
            lambda value: value["files"][0].update(sha256="ABC"),
            BundleErrorCode.INVALID_MANIFEST,
        ),
        (
            lambda value: value["files"].reverse(),
            BundleErrorCode.INVALID_MANIFEST,
        ),
        (
            lambda value: value["files"].pop(),
            BundleErrorCode.INVALID_MANIFEST,
        ),
        (
            lambda value: value.update(files=value["files"] * 2),
            BundleErrorCode.RESOURCE_LIMIT_EXCEEDED,
        ),
    ],
)
def test_reader_rejects_invalid_manifest_contract(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
    mutation,
    code,
) -> None:
    directory = CanonicalArtifactFileBundleAdapter().write(
        canonical_file_bundle,
        tmp_path / "bundle",
    )
    manifest = _read_manifest(directory)
    mutation(manifest)
    _write_manifest(directory, manifest)

    with pytest.raises(BundleContractError) as captured:
        CanonicalArtifactFileBundleAdapter().read(directory)

    assert captured.value.code is code


@pytest.mark.parametrize(
    "data",
    [
        b"not-json\n",
        b"\xff",
        b'{"duplicate":1,"duplicate":2}\n',
        b'{"number":NaN}\n',
        b"{}",
        b"[]\n",
    ],
)
def test_reader_rejects_invalid_or_noncanonical_manifest_json(
    tmp_path: Path,
    data: bytes,
) -> None:
    directory = tmp_path / "bundle"
    directory.mkdir()
    (directory / MANIFEST_FILE).write_bytes(data)

    with pytest.raises(BundleContractError) as captured:
        CanonicalArtifactFileBundleAdapter().read(directory)

    expected = (
        BundleErrorCode.INVALID_MANIFEST
        if data == b"[]\n"
        else BundleErrorCode.INVALID_JSON
    )
    assert captured.value.code is expected


def test_reader_enforces_directory_resource_and_regular_file_limits(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = CanonicalArtifactFileBundleAdapter()
    too_many = adapter.write(canonical_file_bundle, tmp_path / "too-many")
    monkeypatch.setattr(bundle_module, "_MAX_FILES", 1)
    with pytest.raises(BundleContractError) as captured:
        adapter.read(too_many)
    assert captured.value.code is BundleErrorCode.RESOURCE_LIMIT_EXCEEDED

    monkeypatch.setattr(bundle_module, "_MAX_FILES", 20)
    nested = adapter.write(canonical_file_bundle, tmp_path / "nested")
    (nested / "subdirectory").mkdir()
    with pytest.raises(BundleContractError) as captured:
        adapter.read(nested)
    assert captured.value.code is BundleErrorCode.UNDECLARED_FILE

    limited = adapter.write(canonical_file_bundle, tmp_path / "limited")
    monkeypatch.setattr(bundle_module, "_MAX_MANIFEST_BYTES", 1)
    with pytest.raises(BundleContractError) as captured:
        adapter.read(limited)
    assert captured.value.code is BundleErrorCode.RESOURCE_LIMIT_EXCEEDED


@pytest.mark.parametrize("unsafe_name", ["../manifest.json", "nested/file.csv"])
def test_reader_rejects_unsafe_zip_paths(tmp_path: Path, unsafe_name: str) -> None:
    source = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(unsafe_name, b"data")

    with pytest.raises(BundleContractError) as captured:
        CanonicalArtifactFileBundleAdapter().read(source)

    assert captured.value.code is BundleErrorCode.UNSAFE_ARCHIVE


def test_reader_rejects_bad_zip_and_zip_resource_limits(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = tmp_path / "bad.zip"
    bad.write_text("not zip")
    with pytest.raises(BundleContractError) as captured:
        CanonicalArtifactFileBundleAdapter().read(bad)
    assert captured.value.code is BundleErrorCode.UNSAFE_ARCHIVE

    valid = CanonicalArtifactFileBundleAdapter().write(
        canonical_file_bundle,
        tmp_path / "valid.zip",
    )
    monkeypatch.setattr(bundle_module, "_MAX_FILES", 1)
    with pytest.raises(BundleContractError) as captured:
        CanonicalArtifactFileBundleAdapter().read(valid)
    assert captured.value.code is BundleErrorCode.RESOURCE_LIMIT_EXCEEDED


def test_reader_enforces_zip_entry_and_total_size_limits(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = CanonicalArtifactFileBundleAdapter().write(
        canonical_file_bundle,
        tmp_path / "bundle.zip",
    )
    monkeypatch.setattr(bundle_module, "_MAX_FILE_BYTES", 1)
    with pytest.raises(BundleContractError) as captured:
        CanonicalArtifactFileBundleAdapter().read(archive)
    assert captured.value.code is BundleErrorCode.RESOURCE_LIMIT_EXCEEDED

    monkeypatch.setattr(bundle_module, "_MAX_FILE_BYTES", 512_000_000)
    monkeypatch.setattr(bundle_module, "_MAX_TOTAL_BYTES", 1)
    with pytest.raises(BundleContractError) as captured:
        CanonicalArtifactFileBundleAdapter().read(archive)
    assert captured.value.code is BundleErrorCode.RESOURCE_LIMIT_EXCEEDED


def test_reader_rejects_total_bundle_limit(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = CanonicalArtifactFileBundleAdapter().write(
        canonical_file_bundle,
        tmp_path / "bundle",
    )
    monkeypatch.setattr(bundle_module, "_MAX_TOTAL_BYTES", 1)

    with pytest.raises(BundleContractError) as captured:
        CanonicalArtifactFileBundleAdapter().read(directory)

    assert captured.value.code is BundleErrorCode.RESOURCE_LIMIT_EXCEEDED


def test_writer_rejects_unsafe_existing_destination_types(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    adapter = CanonicalArtifactFileBundleAdapter()
    zip_directory = tmp_path / "bundle.zip"
    zip_directory.mkdir()
    with pytest.raises(BundleContractError) as captured:
        adapter.write(canonical_file_bundle, zip_directory, overwrite=True)
    assert captured.value.code is BundleErrorCode.DESTINATION_TYPE_UNSUPPORTED

    directory_file = tmp_path / "bundle"
    directory_file.write_text("file")
    with pytest.raises(BundleContractError) as captured:
        adapter.write(canonical_file_bundle, directory_file, overwrite=True)
    assert captured.value.code is BundleErrorCode.DESTINATION_TYPE_UNSUPPORTED

    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    os.symlink(target, link)
    with pytest.raises(BundleContractError) as captured:
        adapter.write(canonical_file_bundle, link, overwrite=True)
    assert captured.value.code is BundleErrorCode.DESTINATION_TYPE_UNSUPPORTED


def test_directory_overwrite_detects_stale_backup(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    adapter = CanonicalArtifactFileBundleAdapter()
    destination = adapter.write(canonical_file_bundle, tmp_path / "bundle")
    (tmp_path / ".bundle.backup").mkdir()

    with pytest.raises(BundleContractError) as captured:
        adapter.write(canonical_file_bundle, destination, overwrite=True)

    assert captured.value.code is BundleErrorCode.WRITE_FAILED
    assert adapter.read(destination) == canonical_file_bundle


def test_directory_overwrite_restores_original_after_write_failure(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = CanonicalArtifactFileBundleAdapter()
    destination = adapter.write(canonical_file_bundle, tmp_path / "bundle")
    original_manifest = (destination / MANIFEST_FILE).read_bytes()

    def fail_write(payload, path) -> None:
        raise OSError("simulated failure")

    monkeypatch.setattr(bundle_module, "_write_directory", fail_write)
    with pytest.raises(BundleContractError) as captured:
        adapter.write(canonical_file_bundle, destination, overwrite=True)

    assert captured.value.code is BundleErrorCode.WRITE_FAILED
    assert (destination / MANIFEST_FILE).read_bytes() == original_manifest


def test_new_directory_write_cleans_temporary_data_after_atomic_failure(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_replace = bundle_module.os.replace

    def fail_replace(source, destination) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(bundle_module.os, "replace", fail_replace)
    with pytest.raises(BundleContractError) as captured:
        CanonicalArtifactFileBundleAdapter().write(
            canonical_file_bundle,
            tmp_path / "bundle",
        )
    monkeypatch.setattr(bundle_module.os, "replace", real_replace)

    assert captured.value.code is BundleErrorCode.WRITE_FAILED
    assert not (tmp_path / "bundle").exists()
    assert not tuple(tmp_path.glob(".bundle.*"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bundle_schema_version", "2.0"),
        ("artifact_schema_version", "2.0"),
    ],
)
def test_reader_rejects_unknown_schema_versions(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
    field: str,
    value: str,
) -> None:
    directory = CanonicalArtifactFileBundleAdapter().write(
        canonical_file_bundle,
        tmp_path / field,
    )
    manifest = _read_manifest(directory)
    manifest[field] = value
    _write_manifest(directory, manifest)

    with pytest.raises(BundleContractError) as captured:
        CanonicalArtifactFileBundleAdapter().read(directory)

    assert captured.value.code is BundleErrorCode.UNSUPPORTED_SCHEMA_VERSION


def test_reader_rejects_unknown_trade_fill_link(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    directory = CanonicalArtifactFileBundleAdapter().write(
        canonical_file_bundle,
        tmp_path / "bundle",
    )
    _replace_payload(
        directory,
        "trade_fills.csv",
        b"trade_id,fill_id\nunknown,fill-1\n",
        record_count=1,
    )

    with pytest.raises(BundleContractError) as captured:
        CanonicalArtifactFileBundleAdapter().read(directory)

    assert captured.value.code is BundleErrorCode.INVALID_ROW
    assert "unknown trade" in str(captured.value)


def test_reader_rejects_symbolic_link_source(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    target = CanonicalArtifactFileBundleAdapter().write(
        canonical_file_bundle,
        tmp_path / "target.zip",
    )
    link = tmp_path / "link.zip"
    os.symlink(target, link)

    with pytest.raises(BundleContractError) as captured:
        CanonicalArtifactFileBundleAdapter().read(link)

    assert captured.value.code is BundleErrorCode.SOURCE_TYPE_UNSUPPORTED


def test_error_string_exposes_stable_context() -> None:
    error = BundleContractError(
        BundleErrorCode.INVALID_ROW,
        "invalid value",
        file_path="fills.csv",
        row_number=2,
        field="price",
    )

    assert str(error) == (
        "invalid_row: invalid value (file=fills.csv, row=2, field=price)"
    )


def test_manifest_mutation_helper_does_not_modify_original() -> None:
    value = {"bundle_content_sha256": "x", "nested": {"x": 1}}
    copied = deepcopy(value)
    _content_identity(copied)
    assert copied == value
