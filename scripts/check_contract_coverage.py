from era100x.contracts.models import CONTRACT_TYPES


def main() -> int:
    expected = 15
    if len(CONTRACT_TYPES) != expected:
        print(f"contract coverage mismatch: {len(CONTRACT_TYPES)}/{expected}")
        return 1
    if any(not model.model_fields for model in CONTRACT_TYPES):
        return 1
    print(f"Appendix C-E contract coverage: {len(CONTRACT_TYPES)}/{expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
