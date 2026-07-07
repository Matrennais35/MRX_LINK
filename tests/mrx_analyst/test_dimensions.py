"""Tests for dimension discovery (parsing the real MRX reference tables)."""

from mrx_analyst.mrx import dimensions


def test_parses_all_three_tables_with_plausible_counts():
    dims = dimensions.all_dimensions()
    by_axis = {}
    for d in dims:
        by_axis[d.axis] = by_axis.get(d.axis, 0) + 1
    assert by_axis["row"] >= 300        # row_selection.md is ~360 codes
    assert by_axis["column"] >= 100
    assert by_axis["risk_type"] >= 60


def test_no_header_or_separator_rows_leak_into_the_catalog():
    dims = dimensions.all_dimensions()
    assert all(d.code and set(d.code) != {"-"} for d in dims)
    assert not any(d.display.lower() == "display name" for d in dims)


def test_find_locates_known_breakdowns_by_display_name():
    # Spot-checks against codes verified in the real row_selection.md.
    assert any(d.code == "RowGrpPrdInlNo" for d in dimensions.find("Deal/Security"))
    assert any(d.code == "RowGrpCurrency" for d in dimensions.find("currency", axis="row"))
    assert any(d.code == "EQDELTACASH" for d in dimensions.find("EQ Delta Cash"))


def test_find_is_axis_scoped():
    assert dimensions.find("EQ Delta Cash", axis="row") == []


def test_catalog_text_groups_by_axis_and_maps_display_to_code():
    text = dimensions.catalog_text()
    assert "ROW GROUPINGS" in text
    assert "RISK TYPES" in text
    assert "Deal/Security -> RowGrpPrdInlNo" in text


def test_catalog_text_can_be_restricted_to_one_axis():
    text = dimensions.catalog_text(axis="risk_type")
    assert "RISK TYPES" in text
    assert "ROW GROUPINGS" not in text
