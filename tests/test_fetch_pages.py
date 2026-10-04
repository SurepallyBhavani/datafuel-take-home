"""sweep.fetch_all_pages: paging, duplicates and the checks on each page. get_json is replaced by queued fake pages."""
import pytest

import sweep


def page(items, next_cursor=None, store_id="MUM-001", source="origin", partial=False):
    return {"store_id": store_id, "items": items, "partial": partial, "next_cursor": next_cursor,
            "meta": {"source": source}}


def item(sku, in_stock=True, qty=1):
    return {"sku_id": sku, "name": sku, "in_stock": in_stock, "qty": qty, "price": 1.0,
            "observed_at": "2026-09-28T04:37:00Z"}


@pytest.fixture
def fetch(monkeypatch):
    """fetch(bodies) queues the pages, runs fetch_all_pages, and returns (items, code, text, cursors asked for)."""
    cursors = []

    def run(bodies):
        queue = list(bodies)

        def fake_get_json(path, params, counts):
            cursors.append(params["cursor"])
            return queue.pop(0), None

        monkeypatch.setattr(sweep, "get_json", fake_get_json)
        cursors.clear()
        items, code, text = sweep.fetch_all_pages("MUM-001", "2026-09-28T04:30:00Z", {"attempts": 0})
        return items, code, text, list(cursors)

    return run


def skus(items):
    return sorted(i["sku_id"] for i in items)


def test_follows_the_cursor_to_the_last_page(fetch):
    items, code, text, cursors = fetch([page([item("A")], "15"), page([item("B")], "30"), page([item("C")])])
    assert cursors == ["0", "15", "30"]
    assert (code, text) == (None, None)
    assert skus(items) == ["A", "B", "C"]


def test_a_product_repeated_at_a_page_boundary_is_kept_once(fetch):
    items, code, _, _ = fetch([page([item("A"), item("B")], "2"), page([item("B"), item("C")])])
    assert code is None
    assert skus(items) == ["A", "B", "C"]


def test_a_product_repeated_with_different_values_makes_the_store_incomplete(fetch):
    items, code, text, _ = fetch([page([item("A", in_stock=True)], "1"), page([item("A", in_stock=False, qty=0)])])
    assert items is None
    assert code == "conflicting_duplicate" and "SKU" not in text and "A appeared twice" in text


def test_reply_from_the_edge_is_a_soft_ban_and_returns_no_items(fetch):
    items, code, text, _ = fetch([page([item("A")], source="edge")])
    assert items is None
    assert code == "soft_banned" and "edge" in text


def test_reply_with_no_meta_is_treated_as_a_soft_ban(fetch):
    body = page([item("A")])
    del body["meta"]
    items, code, _, _ = fetch([body])
    assert (items, code) == (None, "soft_banned")


def test_ban_on_a_later_page_throws_away_the_earlier_good_page(fetch):
    items, code, _, cursors = fetch([page([item("A")], "15"), page([item("B")], source="edge")])
    assert (items, code) == (None, "soft_banned")
    assert cursors == ["0", "15"]


def test_partial_reply_makes_the_store_incomplete_and_returns_no_items(fetch):
    items, code, text, _ = fetch([page([], partial=True)])
    assert (items, code) == (None, "partial")
    assert "partial" in text


def test_reply_for_another_store_is_refused(fetch):
    items, code, text, _ = fetch([page([item("A")], store_id="MUM-002")])
    assert (items, code) == (None, "fetch_failed")
    assert "MUM-002" in text


def test_a_cursor_that_never_ends_stops_at_the_page_limit(fetch):
    items, code, text, cursors = fetch([page([item("S%d" % i)], "next") for i in range(sweep.MAX_PAGES + 5)])
    assert (items, code) == (None, "fetch_failed")
    assert len(cursors) == sweep.MAX_PAGES and "pages" in text


def test_a_page_that_cannot_be_fetched_makes_the_store_incomplete_with_the_reason(monkeypatch):
    monkeypatch.setattr(sweep, "get_json", lambda path, params, counts: (None, "gave up after 6 attempts, last error: HTTP 503"))
    items, code, text = sweep.fetch_all_pages("MUM-001", "2026-09-28T04:30:00Z", {"attempts": 0})
    assert (items, code) == (None, "fetch_failed")
    assert text == "gave up after 6 attempts, last error: HTTP 503"


def test_store_with_no_products_gives_an_empty_list_not_an_error(fetch):
    items, code, _, _ = fetch([page([])])
    assert items == [] and code is None
