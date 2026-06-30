from research_core.p4_canonical_freeze.p4_freeze_rule_audit import canonical_config, config_hash


def test_config_hash_stable_for_same_config():
    assert config_hash(canonical_config("abc")) == config_hash(canonical_config("abc"))


def test_config_hash_changes_when_config_changes():
    cfg = canonical_config("abc")
    changed = dict(cfg)
    changed["leverage_mode"] = "fixed_2x"
    assert config_hash(cfg) != config_hash(changed)

