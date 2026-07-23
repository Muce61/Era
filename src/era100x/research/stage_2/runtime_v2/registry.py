"""Manifest-authorized, fail-closed Runtime V2 plugin registry."""

from __future__ import annotations

from dataclasses import dataclass

from era100x.research.stage_2.runtime_v2.contracts import (
    EvidenceCapability,
    FeatureBatch,
)
from era100x.research.stage_2.runtime_v2.plugins import (
    ContextPlugin,
    PluginKind,
    PluginInvocation,
    ResearchSetupPlugin,
    RuntimePluginApproval,
    RuntimePluginDescriptor,
    RuntimeVariantApproval,
)

_CAPABILITY_RANK: dict[EvidenceCapability, int] = {"H1": 1, "H2": 2}
_GROUP1_SETUP = ("KEY_LOW_SWEEP_RECLAIM_HOLD_V1", "1.0")
_GROUP1_CONTEXT = ("CAUSAL_EMA20_1H", "1.0")
_GROUP1_VARIANTS = {("V1_PRICE", "1.0"), ("V1_FLOW", "1.0")}
_FORBIDDEN_PLUGIN_ATTRIBUTES = {
    "stage1",
    "stage1_reader",
    "stage1_store",
    "file_path",
    "filesystem",
    "file_reader",
    "network",
    "http_client",
    "session",
    "path",
    "root",
    "url",
    "socket",
    "price_feature_store",
    "trade_primitive_store",
    "trade_row_group_index",
    "event_fact_store",
}


class RuntimeApprovalError(ValueError):
    """Raised whenever runtime authority is missing, ambiguous, or changed."""


@dataclass(frozen=True, slots=True)
class ApprovedRuntimeBinding:
    setup: ResearchSetupPlugin
    context: ContextPlugin
    variant: RuntimeVariantApproval

    @property
    def required_feature_hashes(self) -> tuple[str, ...]:
        values = {
            item.definition_hash
            for descriptor in (self.setup.descriptor, self.context.descriptor)
            for item in descriptor.required_features
        }
        values.update(self.variant.required_feature_hashes)
        return tuple(sorted(values))


class ApprovedRuntimeRegistry:
    """Bind implementations only when an immutable approval exactly matches.

    Approval records are constructor inputs from a locked Manifest; plugin code
    cannot self-register as approved.  Unknown IDs, test-only additions, changed
    implementation trees, and any external-access surface fail closed.
    """

    def __init__(
        self,
        plugin_approvals: tuple[RuntimePluginApproval, ...],
        variant_approvals: tuple[RuntimeVariantApproval, ...],
    ) -> None:
        self._plugin_approvals: dict[tuple[str, str, str], RuntimePluginApproval] = {}
        self._variant_approvals: dict[tuple[str, str], RuntimeVariantApproval] = {}
        self._setups: dict[tuple[str, str], ResearchSetupPlugin] = {}
        self._contexts: dict[tuple[str, str], ContextPlugin] = {}
        for plugin_approval in plugin_approvals:
            key = (
                plugin_approval.plugin_kind,
                plugin_approval.plugin_id,
                plugin_approval.plugin_version,
            )
            if key in self._plugin_approvals:
                raise RuntimeApprovalError(f"duplicate plugin approval: {key}")
            self._plugin_approvals[key] = plugin_approval
        for variant_approval in variant_approvals:
            variant_key = (variant_approval.variant_id, variant_approval.variant_version)
            if variant_key in self._variant_approvals:
                raise RuntimeApprovalError(f"duplicate variant approval: {variant_key}")
            self._variant_approvals[variant_key] = variant_approval
        if not self._plugin_approvals or not self._variant_approvals:
            raise RuntimeApprovalError("runtime registry requires explicit locked approvals")

    @classmethod
    def for_group1(
        cls,
        plugin_approvals: tuple[RuntimePluginApproval, ...],
        variant_approvals: tuple[RuntimeVariantApproval, ...],
    ) -> ApprovedRuntimeRegistry:
        registry = cls(plugin_approvals, variant_approvals)
        setup_keys = {
            (item.plugin_id, item.plugin_version)
            for item in plugin_approvals
            if item.plugin_kind == "SETUP"
        }
        context_keys = {
            (item.plugin_id, item.plugin_version)
            for item in plugin_approvals
            if item.plugin_kind == "CONTEXT"
        }
        variant_keys = {(item.variant_id, item.variant_version) for item in variant_approvals}
        if setup_keys != {_GROUP1_SETUP}:
            raise RuntimeApprovalError("Group-1 registry permits exactly the approved setup")
        if context_keys != {_GROUP1_CONTEXT}:
            raise RuntimeApprovalError("Group-1 registry permits exactly the approved context")
        if variant_keys != _GROUP1_VARIANTS:
            raise RuntimeApprovalError("Group-1 registry permits exactly V1_PRICE and V1_FLOW")
        return registry

    def bind_setup(self, plugin: ResearchSetupPlugin) -> None:
        descriptor = self._bind(plugin, expected_kind="SETUP", method="evaluate_setup")
        key = (descriptor.plugin_id, descriptor.plugin_version)
        if key in self._setups:
            raise RuntimeApprovalError(f"setup implementation already bound: {key}")
        self._setups[key] = plugin

    def bind_context(self, plugin: ContextPlugin) -> None:
        descriptor = self._bind(plugin, expected_kind="CONTEXT", method="evaluate_context")
        key = (descriptor.plugin_id, descriptor.plugin_version)
        if key in self._contexts:
            raise RuntimeApprovalError(f"context implementation already bound: {key}")
        self._contexts[key] = plugin

    def require_setup(self, plugin_id: str, plugin_version: str) -> ResearchSetupPlugin:
        try:
            return self._setups[(plugin_id, plugin_version)]
        except KeyError as exc:
            raise RuntimeApprovalError("unknown or unbound setup plugin") from exc

    def require_context(self, plugin_id: str, plugin_version: str) -> ContextPlugin:
        try:
            return self._contexts[(plugin_id, plugin_version)]
        except KeyError as exc:
            raise RuntimeApprovalError("unknown or unbound context plugin") from exc

    def require_variant(
        self,
        variant_id: str,
        variant_version: str,
        evidence_capability: EvidenceCapability,
    ) -> RuntimeVariantApproval:
        if evidence_capability not in _CAPABILITY_RANK:
            raise RuntimeApprovalError("unknown evidence capability")
        try:
            variant = self._variant_approvals[(variant_id, variant_version)]
        except KeyError as exc:
            raise RuntimeApprovalError("unknown or unapproved runtime variant") from exc
        if _CAPABILITY_RANK[evidence_capability] < _CAPABILITY_RANK[variant.required_capability]:
            raise RuntimeApprovalError("insufficient evidence capability for runtime variant")
        return variant

    def resolve(
        self,
        *,
        setup_id: str,
        setup_version: str,
        context_id: str,
        context_version: str,
        variant_id: str,
        variant_version: str,
        evidence_capability: EvidenceCapability,
    ) -> ApprovedRuntimeBinding:
        setup = self.require_setup(setup_id, setup_version)
        context = self.require_context(context_id, context_version)
        variant = self.require_variant(variant_id, variant_version, evidence_capability)
        for descriptor in (setup.descriptor, context.descriptor):
            for requirement in descriptor.required_features:
                if (
                    _CAPABILITY_RANK[evidence_capability]
                    < _CAPABILITY_RANK[requirement.required_capability]
                ):
                    raise RuntimeApprovalError(
                        "insufficient evidence capability for plugin Feature Definition"
                    )
        return ApprovedRuntimeBinding(setup=setup, context=context, variant=variant)

    def execute_context(
        self, plugin_id: str, plugin_version: str, invocation: PluginInvocation
    ) -> FeatureBatch:
        plugin = self.require_context(plugin_id, plugin_version)
        self._validate_invocation(plugin.descriptor, invocation)
        result = plugin.evaluate_context(invocation)
        self._validate_output(plugin.descriptor, invocation, result)
        return result

    def execute_setup(
        self,
        plugin_id: str,
        plugin_version: str,
        invocation: PluginInvocation,
        context: FeatureBatch,
    ) -> FeatureBatch:
        plugin = self.require_setup(plugin_id, plugin_version)
        self._validate_invocation(plugin.descriptor, invocation)
        if context.instrument != invocation.instrument:
            raise RuntimeApprovalError("setup context cannot mix instruments")
        context.require_available_as_of(invocation.as_of_ns)
        result = plugin.evaluate_setup(invocation, context)
        self._validate_output(plugin.descriptor, invocation, result)
        return result

    def _bind(
        self,
        plugin: ResearchSetupPlugin | ContextPlugin,
        *,
        expected_kind: PluginKind,
        method: str,
    ) -> RuntimePluginDescriptor:
        try:
            descriptor = plugin.descriptor
        except AttributeError as exc:
            raise RuntimeApprovalError("plugin lacks a Runtime V2 descriptor") from exc
        if not isinstance(descriptor, RuntimePluginDescriptor):
            raise RuntimeApprovalError("plugin descriptor has the wrong Runtime V2 type")
        if descriptor.plugin_kind != expected_kind:
            raise RuntimeApprovalError("plugin kind does not match its registry surface")
        if not callable(getattr(plugin, method, None)):
            raise RuntimeApprovalError(f"plugin lacks required pure method: {method}")
        policy = descriptor.access_policy
        if (
            policy.stage1_access != "FORBIDDEN"
            or policy.filesystem_access != "FORBIDDEN"
            or policy.network_access != "FORBIDDEN"
        ):
            raise RuntimeApprovalError("plugin requests forbidden external access")
        exposed = sorted(name for name in _FORBIDDEN_PLUGIN_ATTRIBUTES if hasattr(plugin, name))
        if exposed:
            raise RuntimeApprovalError(f"plugin exposes forbidden runtime dependencies: {exposed}")
        key = (descriptor.plugin_kind, descriptor.plugin_id, descriptor.plugin_version)
        try:
            approval = self._plugin_approvals[key]
        except KeyError as exc:
            raise RuntimeApprovalError("plugin is not in the locked approval manifest") from exc
        if descriptor.descriptor_hash != approval.descriptor_hash:
            raise RuntimeApprovalError("plugin descriptor differs from locked approval")
        if descriptor.implementation_tree_hash != approval.implementation_tree_hash:
            raise RuntimeApprovalError("plugin implementation tree differs from locked approval")
        return descriptor

    @staticmethod
    def _validate_invocation(
        descriptor: RuntimePluginDescriptor, invocation: PluginInvocation
    ) -> None:
        available = {batch.definition_hash: batch for batch in invocation.batches}
        required = {item.definition_hash: item for item in descriptor.required_features}
        if available.keys() != required.keys():
            raise RuntimeApprovalError(
                "plugin invocation must contain exactly its approved Feature Definitions"
            )
        for definition_hash, requirement in required.items():
            batch = available[definition_hash]
            if (
                batch.definition_id != requirement.definition_id
                or batch.definition_version != requirement.definition_version
            ):
                raise RuntimeApprovalError("Feature Definition identity does not match approval")
            if (
                _CAPABILITY_RANK[batch.evidence_capability]
                < _CAPABILITY_RANK[requirement.required_capability]
            ):
                raise RuntimeApprovalError("FeatureBatch has insufficient evidence capability")

    @staticmethod
    def _validate_output(
        descriptor: RuntimePluginDescriptor,
        invocation: PluginInvocation,
        result: FeatureBatch,
    ) -> None:
        if not isinstance(result, FeatureBatch):
            raise RuntimeApprovalError("plugin output must be a FeatureBatch")
        if result.instrument != invocation.instrument:
            raise RuntimeApprovalError("plugin output cannot change instrument")
        if result.window != invocation.owner_window:
            raise RuntimeApprovalError("plugin output must retain the invocation owner window")
        if result.schema_hash != descriptor.output_schema_hash:
            raise RuntimeApprovalError("plugin output schema differs from approved descriptor")
        try:
            result.require_available_as_of(invocation.as_of_ns)
        except ValueError as exc:
            raise RuntimeApprovalError("plugin output uses unavailable future facts") from exc


def as_setup_plugin(value: object) -> ResearchSetupPlugin:
    """Typed helper for callers loading plugins from an approved static module."""

    if not isinstance(value, ResearchSetupPlugin):
        raise RuntimeApprovalError("object does not implement ResearchSetupPlugin")
    return value


def as_context_plugin(value: object) -> ContextPlugin:
    if not isinstance(value, ContextPlugin):
        raise RuntimeApprovalError("object does not implement ContextPlugin")
    return value
