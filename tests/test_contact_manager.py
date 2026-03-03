"""
Tests for Contact Manager
"""

import json

import pytest

from gateway.contact_manager import ContactManager


@pytest.fixture
def cm(tmp_path):
    db = str(tmp_path / "test_contacts.db")
    manager = ContactManager(db_path=db)
    yield manager
    manager.close()


@pytest.fixture
def sample_contact(cm):
    return cm.create_contact(
        contact_id="c1",
        name="Alice",
        email="alice@example.com",
        phone="+1234567890",
        preferred_channel="telegram",
        metadata={"source": "web"},
    )


# ── Contact CRUD ─────────────────────────────────────────

def test_create_contact(cm):
    c = cm.create_contact("c1", "Alice", email="alice@test.com")
    assert c["id"] == "c1"
    assert c["name"] == "Alice"
    assert c["email"] == "alice@test.com"
    assert c["opted_out"] == 0


def test_get_contact(cm, sample_contact):
    c = cm.get_contact("c1")
    assert c is not None
    assert c["name"] == "Alice"
    assert c["metadata"] == {"source": "web"}
    assert "channels" in c
    assert "tags" in c
    assert "groups" in c


def test_get_contact_not_found(cm):
    assert cm.get_contact("nonexistent") is None


def test_update_contact(cm, sample_contact):
    c = cm.update_contact("c1", name="Alice Smith", email="alice.smith@test.com")
    assert c["name"] == "Alice Smith"
    assert c["email"] == "alice.smith@test.com"


def test_update_contact_metadata(cm, sample_contact):
    c = cm.update_contact("c1", metadata={"source": "api", "tier": "premium"})
    assert c["metadata"]["tier"] == "premium"


def test_update_contact_no_changes(cm, sample_contact):
    c = cm.update_contact("c1")
    assert c["name"] == "Alice"


def test_delete_contact(cm, sample_contact):
    assert cm.delete_contact("c1") is True
    assert cm.get_contact("c1") is None


def test_delete_contact_not_found(cm):
    assert cm.delete_contact("nonexistent") is False


def test_list_contacts(cm):
    cm.create_contact("c1", "Alice")
    cm.create_contact("c2", "Bob")
    cm.create_contact("c3", "Charlie")
    contacts = cm.list_contacts()
    assert len(contacts) == 3


def test_list_contacts_limit(cm):
    for i in range(10):
        cm.create_contact(f"c{i}", f"User{i}")
    contacts = cm.list_contacts(limit=5)
    assert len(contacts) == 5


def test_list_contacts_excludes_opted_out(cm):
    cm.create_contact("c1", "Alice")
    cm.create_contact("c2", "Bob")
    cm.opt_out("c2")
    contacts = cm.list_contacts(include_opted_out=False)
    assert len(contacts) == 1


def test_list_contacts_includes_opted_out(cm):
    cm.create_contact("c1", "Alice")
    cm.create_contact("c2", "Bob")
    cm.opt_out("c2")
    contacts = cm.list_contacts(include_opted_out=True)
    assert len(contacts) == 2


def test_count_contacts(cm):
    cm.create_contact("c1", "Alice")
    cm.create_contact("c2", "Bob")
    assert cm.count_contacts() == 2


# ── Channel Management ──────────────────────────────────

def test_add_channel(cm, sample_contact):
    cm.add_channel("c1", "telegram", "123456")
    c = cm.get_contact("c1")
    assert len(c["channels"]) == 1
    assert c["channels"][0]["channel"] == "telegram"
    assert c["channels"][0]["address"] == "123456"


def test_add_multiple_channels(cm, sample_contact):
    cm.add_channel("c1", "telegram", "123456")
    cm.add_channel("c1", "email", "alice@test.com")
    c = cm.get_contact("c1")
    assert len(c["channels"]) == 2


def test_remove_channel(cm, sample_contact):
    cm.add_channel("c1", "telegram", "123456")
    assert cm.remove_channel("c1", "telegram") is True
    c = cm.get_contact("c1")
    assert len(c["channels"]) == 0


def test_remove_channel_not_found(cm, sample_contact):
    assert cm.remove_channel("c1", "nonexistent") is False


def test_get_channel_address(cm, sample_contact):
    cm.add_channel("c1", "telegram", "123456")
    addr = cm.get_channel_address("c1", "telegram")
    assert addr == "123456"


def test_get_channel_address_not_found(cm, sample_contact):
    assert cm.get_channel_address("c1", "telegram") is None


def test_get_contacts_by_channel(cm):
    cm.create_contact("c1", "Alice")
    cm.create_contact("c2", "Bob")
    cm.add_channel("c1", "telegram", "111")
    cm.add_channel("c2", "telegram", "222")
    contacts = cm.get_contacts_by_channel("telegram")
    assert len(contacts) == 2


# ── Tag Management ───────────────────────────────────────

def test_add_tag(cm, sample_contact):
    cm.add_tag("c1", "vip")
    tags = cm.get_tags("c1")
    assert "vip" in tags


def test_add_tags_bulk(cm, sample_contact):
    cm.add_tags("c1", ["vip", "premium", "active"])
    tags = cm.get_tags("c1")
    assert len(tags) == 3


def test_add_tag_idempotent(cm, sample_contact):
    cm.add_tag("c1", "vip")
    cm.add_tag("c1", "vip")
    tags = cm.get_tags("c1")
    assert tags.count("vip") == 1


def test_remove_tag(cm, sample_contact):
    cm.add_tag("c1", "vip")
    assert cm.remove_tag("c1", "vip") is True
    assert "vip" not in cm.get_tags("c1")


def test_remove_tag_not_found(cm, sample_contact):
    assert cm.remove_tag("c1", "nonexistent") is False


def test_get_contacts_by_tag(cm):
    cm.create_contact("c1", "Alice")
    cm.create_contact("c2", "Bob")
    cm.add_tag("c1", "vip")
    cm.add_tag("c2", "vip")
    contacts = cm.get_contacts_by_tag("vip")
    assert len(contacts) == 2


def test_get_contacts_by_tags_or(cm):
    cm.create_contact("c1", "Alice")
    cm.create_contact("c2", "Bob")
    cm.add_tag("c1", "vip")
    cm.add_tag("c2", "premium")
    contacts = cm.get_contacts_by_tags(["vip", "premium"], match_all=False)
    assert len(contacts) == 2


def test_get_contacts_by_tags_and(cm):
    cm.create_contact("c1", "Alice")
    cm.create_contact("c2", "Bob")
    cm.add_tags("c1", ["vip", "premium"])
    cm.add_tag("c2", "vip")
    contacts = cm.get_contacts_by_tags(["vip", "premium"], match_all=True)
    assert len(contacts) == 1
    assert contacts[0]["id"] == "c1"


def test_get_contacts_by_tags_empty(cm):
    assert cm.get_contacts_by_tags([]) == []


def test_get_all_tags(cm):
    cm.create_contact("c1", "Alice")
    cm.create_contact("c2", "Bob")
    cm.add_tags("c1", ["vip", "active"])
    cm.add_tag("c2", "vip")
    all_tags = cm.get_all_tags()
    assert len(all_tags) == 2
    # vip should have count 2
    vip = next(t for t in all_tags if t["tag"] == "vip")
    assert vip["count"] == 2


# ── Group Management ─────────────────────────────────────

def test_create_group(cm):
    g = cm.create_group("g1", "VIP Customers", description="Top tier")
    assert g["id"] == "g1"
    assert g["name"] == "VIP Customers"
    assert g["member_count"] == 0


def test_get_group(cm):
    cm.create_group("g1", "VIPs")
    g = cm.get_group("g1")
    assert g is not None
    assert g["name"] == "VIPs"


def test_get_group_not_found(cm):
    assert cm.get_group("nonexistent") is None


def test_delete_group(cm):
    cm.create_group("g1", "VIPs")
    assert cm.delete_group("g1") is True
    assert cm.get_group("g1") is None


def test_list_groups(cm):
    cm.create_group("g1", "Alpha")
    cm.create_group("g2", "Beta")
    groups = cm.list_groups()
    assert len(groups) == 2


def test_add_to_group(cm, sample_contact):
    cm.create_group("g1", "VIPs")
    cm.add_to_group("c1", "g1")
    g = cm.get_group("g1")
    assert g["member_count"] == 1


def test_add_to_group_idempotent(cm, sample_contact):
    cm.create_group("g1", "VIPs")
    cm.add_to_group("c1", "g1")
    cm.add_to_group("c1", "g1")
    g = cm.get_group("g1")
    assert g["member_count"] == 1


def test_remove_from_group(cm, sample_contact):
    cm.create_group("g1", "VIPs")
    cm.add_to_group("c1", "g1")
    assert cm.remove_from_group("c1", "g1") is True
    g = cm.get_group("g1")
    assert g["member_count"] == 0


def test_get_group_members(cm):
    cm.create_contact("c1", "Alice")
    cm.create_contact("c2", "Bob")
    cm.create_group("g1", "Team")
    cm.add_to_group("c1", "g1")
    cm.add_to_group("c2", "g1")
    members = cm.get_group_members("g1")
    assert len(members) == 2


def test_contact_groups_in_detail(cm, sample_contact):
    cm.create_group("g1", "VIPs")
    cm.create_group("g2", "Leads")
    cm.add_to_group("c1", "g1")
    cm.add_to_group("c1", "g2")
    c = cm.get_contact("c1")
    assert len(c["groups"]) == 2


# ── Opt-out / Unsubscribe ───────────────────────────────

def test_global_opt_out(cm, sample_contact):
    cm.opt_out("c1", reason="Unsubscribed via link")
    assert cm.is_opted_out("c1") is True


def test_channel_opt_out(cm, sample_contact):
    cm.add_channel("c1", "telegram", "123")
    cm.opt_out("c1", channel="telegram")
    assert cm.is_opted_out("c1", channel="telegram") is True
    assert cm.is_opted_out("c1") is False  # Not global


def test_opt_in(cm, sample_contact):
    cm.opt_out("c1")
    cm.opt_in("c1")
    assert cm.is_opted_out("c1") is False


def test_channel_opt_in(cm, sample_contact):
    cm.add_channel("c1", "telegram", "123")
    cm.opt_out("c1", channel="telegram")
    cm.opt_in("c1", channel="telegram")
    assert cm.is_opted_out("c1", channel="telegram") is False


def test_is_opted_out_nonexistent(cm):
    assert cm.is_opted_out("nonexistent") is True


def test_opt_out_history(cm, sample_contact):
    cm.opt_out("c1", reason="spam")
    cm.opt_in("c1", reason="re-engaged")
    history = cm.get_opt_out_history("c1")
    assert len(history) == 2


def test_opted_out_excluded_from_channel_query(cm):
    cm.create_contact("c1", "Alice")
    cm.add_channel("c1", "telegram", "111")
    cm.opt_out("c1")
    contacts = cm.get_contacts_by_channel("telegram")
    assert len(contacts) == 0


def test_channel_opted_out_address_not_returned(cm, sample_contact):
    cm.add_channel("c1", "telegram", "123")
    cm.opt_out("c1", channel="telegram")
    addr = cm.get_channel_address("c1", "telegram")
    assert addr is None


# ── Activity Tracking ────────────────────────────────────

def test_record_sent(cm, sample_contact):
    cm.record_sent("c1")
    cm.record_sent("c1")
    c = cm.get_contact("c1")
    assert c["messages_sent"] == 2
    assert c["last_contacted_at"] is not None


def test_record_received(cm, sample_contact):
    cm.record_received("c1")
    c = cm.get_contact("c1")
    assert c["messages_received"] == 1


# ── Segment Query ────────────────────────────────────────

def test_segment_by_tag(cm):
    cm.create_contact("c1", "Alice")
    cm.create_contact("c2", "Bob")
    cm.add_tag("c1", "vip")
    results = cm.segment_query(tags=["vip"])
    assert len(results) == 1
    assert results[0]["id"] == "c1"


def test_segment_by_group(cm):
    cm.create_contact("c1", "Alice")
    cm.create_contact("c2", "Bob")
    cm.create_group("g1", "VIPs")
    cm.add_to_group("c1", "g1")
    results = cm.segment_query(groups=["g1"])
    assert len(results) == 1


def test_segment_by_channel(cm):
    cm.create_contact("c1", "Alice")
    cm.create_contact("c2", "Bob")
    cm.add_channel("c1", "telegram", "111")
    results = cm.segment_query(channels=["telegram"])
    assert len(results) == 1


def test_segment_by_min_messages(cm):
    cm.create_contact("c1", "Alice")
    cm.create_contact("c2", "Bob")
    cm.record_sent("c1")
    cm.record_sent("c1")
    cm.record_sent("c1")
    results = cm.segment_query(min_messages=3)
    assert len(results) == 1
    assert results[0]["id"] == "c1"


def test_segment_excludes_opted_out(cm):
    cm.create_contact("c1", "Alice")
    cm.add_tag("c1", "vip")
    cm.opt_out("c1")
    results = cm.segment_query(tags=["vip"])
    assert len(results) == 0


# ── Search ───────────────────────────────────────────────

def test_search_by_name(cm):
    cm.create_contact("c1", "Alice Wonder")
    cm.create_contact("c2", "Bob Builder")
    results = cm.search("alice")
    assert len(results) == 1


def test_search_by_email(cm):
    cm.create_contact("c1", "Alice", email="alice@test.com")
    results = cm.search("test.com")
    assert len(results) == 1


def test_search_by_phone(cm):
    cm.create_contact("c1", "Alice", phone="+1234567890")
    results = cm.search("1234")
    assert len(results) == 1


def test_search_no_results(cm):
    cm.create_contact("c1", "Alice")
    results = cm.search("nonexistent")
    assert len(results) == 0


# ── Import / Export ──────────────────────────────────────

def test_export_json(cm):
    cm.create_contact("c1", "Alice", email="alice@test.com")
    cm.create_contact("c2", "Bob")
    export = cm.export_contacts("json")
    data = json.loads(export)
    assert len(data) == 2


def test_export_csv(cm):
    cm.create_contact("c1", "Alice", email="alice@test.com")
    export = cm.export_contacts("csv")
    lines = export.strip().split("\n")
    assert len(lines) == 2  # header + 1 row
    assert "Alice" in lines[1]


def test_import_contacts(cm):
    data = [
        {"id": "c1", "name": "Alice", "email": "alice@test.com"},
        {"id": "c2", "name": "Bob"},
    ]
    result = cm.import_contacts(data)
    assert result["created"] == 2
    assert result["errors"] == 0


def test_import_updates_existing(cm, sample_contact):
    data = [{"id": "c1", "name": "Alice Updated"}]
    result = cm.import_contacts(data)
    assert result["updated"] == 1
    c = cm.get_contact("c1")
    assert c["name"] == "Alice Updated"


# ── Stats ────────────────────────────────────────────────

def test_stats(cm):
    cm.create_contact("c1", "Alice")
    cm.create_contact("c2", "Bob")
    cm.create_group("g1", "VIPs")
    cm.add_tag("c1", "vip")
    cm.add_channel("c1", "telegram", "111")
    cm.record_sent("c1")

    stats = cm.get_stats()
    assert stats["total_contacts"] == 2
    assert stats["active_contacts"] == 2
    assert stats["groups"] == 1
    assert stats["unique_tags"] == 1
    assert stats["by_channel"]["telegram"] == 1
    assert stats["total_messages_sent"] == 1


def test_stats_with_opted_out(cm):
    cm.create_contact("c1", "Alice")
    cm.create_contact("c2", "Bob")
    cm.opt_out("c2")
    stats = cm.get_stats()
    assert stats["active_contacts"] == 1
    assert stats["opted_out"] == 1


# ── Cascade Delete ───────────────────────────────────────

def test_delete_contact_cascades_channels(cm, sample_contact):
    cm.add_channel("c1", "telegram", "123")
    cm.delete_contact("c1")
    assert cm.get_channel_address("c1", "telegram") is None


def test_delete_contact_cascades_tags(cm, sample_contact):
    cm.add_tag("c1", "vip")
    cm.delete_contact("c1")
    assert cm.get_tags("c1") == []


def test_delete_contact_cascades_groups(cm, sample_contact):
    cm.create_group("g1", "VIPs")
    cm.add_to_group("c1", "g1")
    cm.delete_contact("c1")
    members = cm.get_group_members("g1")
    assert len(members) == 0
