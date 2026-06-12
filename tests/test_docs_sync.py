from odracir.docs_sync import (
    END_MARKER,
    START_MARKER,
    build_chinese_status_block,
    build_english_status_block,
    replace_generated_block,
)


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


def test_replace_generated_block_does_not_expand_marker_example() -> None:
    current = f"{START_MARKER}\nCurrent\n{END_MARKER}\n"
    example = f"```text\n{START_MARKER}\n{END_MARKER}\n```\n"
    content = f"# Title\n\n{current}\n[Changelog](CHANGELOG.md)\n\n{example}"
    new = f"{START_MARKER}\nNew\n{END_MARKER}\n"

    result = replace_generated_block(content, new, "[Changelog](CHANGELOG.md)")

    assert "Current" not in result
    assert result.count(START_MARKER) == 2
    assert example in result


def test_replace_generated_block_removes_duplicate_managed_blocks() -> None:
    old = f"{START_MARKER}\nOld\n{END_MARKER}\n"
    duplicate = f"{START_MARKER}\nDuplicate\n{END_MARKER}\n"
    content = f"# Title\n\n{old}\n[Changelog](CHANGELOG.md)\n\n{duplicate}"
    new = f"{START_MARKER}\nNew\n{END_MARKER}\n"

    result = replace_generated_block(content, new, "[Changelog](CHANGELOG.md)")

    assert result.count(START_MARKER) == 1
    assert "New" in result
    assert "Old" not in result
    assert "Duplicate" not in result


def test_generated_status_blocks_keep_figure_commands_in_both_languages() -> None:
    english = build_english_status_block("test", "now")
    chinese = build_chinese_status_block("test", "now")

    for command in ("extract-figures", "analyze-figures", "build-figure-evidence"):
        assert command in english
        assert command in chinese

    assert "review-figure" not in english
    assert "review-figure" not in chinese
