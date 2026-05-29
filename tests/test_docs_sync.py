from odracir.docs_sync import END_MARKER, START_MARKER, replace_generated_block


def test_replace_generated_block_inserts_after_anchor() -> None:
    content = "# Title\n\n[Changelog](CHANGELOG.md)\n\nBody\n"
    block = f"{START_MARKER}\nGenerated\n{END_MARKER}\n"

    result = replace_generated_block(content, block, "[Changelog](CHANGELOG.md)")

    assert "[Changelog](CHANGELOG.md)\n\n<!-- ODRACIR_STATUS_START -->" in result


def test_replace_generated_block_replaces_existing_block() -> None:
    old = f"# Title\n\n{START_MARKER}\nOld\n{END_MARKER}\n\nBody\n"
    new = f"{START_MARKER}\nNew\n{END_MARKER}\n"

    result = replace_generated_block(old, new, "missing")

    assert "New" in result
    assert "Old" not in result
