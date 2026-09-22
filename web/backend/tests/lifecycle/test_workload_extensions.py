"""추가 projection의 부재·구버전 제공자·다중 owner 계약."""
import pytest

from app.lifecycle import ExtensionRegistry


def test_new_projection_methods_have_absent_defaults_and_support_old_providers():
    registry = ExtensionRegistry()
    for registered in (False, True):
        if registered:
            registry.register_judgment_projection(object(), owner='old')
            registry.register_overview_document_projection(object(), owner='old')
        assert registry.notice_ids_with_open_blocking_items(None) == []
        assert registry.open_blocking_item_counts(None, [1, 2]) == {}
        assert registry.notice_ids_for_auto_preparation_status(None, [1, 2], 'blocked') == []
    assert registry.workload_counts(None) == {}


def test_workload_owners_replace_in_place_and_refuse_overlapping_keys():
    from app.lifecycle import WorkloadCount
    class Provider:
        def __init__(self, values):
            self.values = values
        def workload_counts(self, session):
            return self.values
    registry = ExtensionRegistry()
    registry.register_workload_projection(Provider({'one': WorkloadCount(1, None)}), owner='a')
    registry.register_workload_projection(Provider({'two': WorkloadCount(None, 'unavailable')}), owner='b')
    registry.register_workload_projection(Provider({'one': WorkloadCount(3, None)}), owner='a')
    assert list(registry.workload_counts(None)) == ['one', 'two']
    assert registry.workload_counts(None)['one'].count == 3
    assert registry.workload_counts(None)['two'].count is None
    with pytest.raises(ValueError):
        registry.register_workload_projection(Provider({}), owner='')
    registry.register_workload_projection(Provider({'one': WorkloadCount(5, None)}), owner='c')
    with pytest.raises(RuntimeError):
        registry.workload_counts(None)


def test_registry_delegates_new_capabilities_and_restores_workload_owners(empty_extensions):
    from app.lifecycle import WorkloadCount, extension_registry, reset_extension_registry, restore_extension_registry
    class Provider:
        def notice_ids_with_open_blocking_items(self, session):
            assert session == 'session'
            return [3, 5]
        def open_blocking_item_counts(self, session, notice_ids):
            assert session == 'session' and notice_ids == [5]
            return {5: 2}
        def notice_ids_for_auto_preparation_status(self, session, notice_ids, status):
            assert session == 'session' and notice_ids == [5] and status == 'blocked'
            return [5]
        def workload_counts(self, session):
            return {'fixture': WorkloadCount(2, None)}
    provider = Provider()
    registry = empty_extensions
    registry.register_judgment_projection(provider, owner='test')
    registry.register_overview_document_projection(provider, owner='test')
    registry.register_workload_projection(provider, owner='test')
    assert registry.judgment_projection is provider
    assert registry.notice_ids_with_open_blocking_items('session') == [3, 5]
    assert registry.open_blocking_item_counts('session', [5]) == {5: 2}
    assert registry.notice_ids_for_auto_preparation_status('session', [5], 'blocked') == [5]
    fresh = reset_extension_registry()
    try:
        assert fresh.workload_counts(None) == {}
    finally:
        restore_extension_registry(registry)
    assert extension_registry().workload_counts(None) == {'fixture': WorkloadCount(2, None)}


def test_human_check_required_sums_sub_counts_and_propagates_null():
    """합계 키는 두 하위 건수의 합이고 하나라도 셀 수 없으면 셀 수 없다(ADR-0067 결정 5).

    제공자 부재(`null`)를 0으로 접으면 "확인할 일 없음"으로 읽힌다.
    """

    from app.lifecycle import WorkloadCount
    from app.lifecycle.services.workload import _sum_parts

    assert _sum_parts({}) == WorkloadCount(None, 'sub_count_unavailable')
    assert _sum_parts({'overview_human_review': WorkloadCount(2)}) == WorkloadCount(
        None, 'sub_count_unavailable'
    )
    assert _sum_parts({
        'overview_human_review': WorkloadCount(None, 'provider_absent'),
        'blocking_items_open': WorkloadCount(3),
    }) == WorkloadCount(None, 'sub_count_unavailable')
    assert _sum_parts({
        'overview_human_review': WorkloadCount(0),
        'blocking_items_open': WorkloadCount(0),
    }) == WorkloadCount(0, None)
    assert _sum_parts({
        'overview_human_review': WorkloadCount(2),
        'blocking_items_open': WorkloadCount(3),
    }) == WorkloadCount(5, None)
