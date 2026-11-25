"""Shared reporting rules for Hermes subagents, plus a manual delegation-model picker.

The 0.1.0 report-rules registration is unchanged. This version adds the
'hermes subagent-model' command: view, manually select, and persist the
delegation (subagent) provider, model, and reasoning effort.

Ground rules:
- Writes only delegation.provider / delegation.model / delegation.reasoning_effort,
  and the chosen keys land in ONE partial save_config(partial, merge_existing=True) --
  Hermes' own narrow-write pattern (hermes_cli.plugins_state.save_plugin_setting). The
  live config is re-read and the route conflict re-checked immediately before that write,
  so a change another session made while the picker was open survives, and delegation keys
  this command does not manage (fallback_providers, base_url, ...) keep their on-disk values.
- Refuses to write when delegation.backend selects a non-default routing strategy
  (this section is not what that backend reads) or when delegation.base_url pins
  an endpoint a manual provider/model change cannot honour.
- Providers come from Hermes' own configured-provider view plus the canonical
  provider list; model candidates come from config.yaml and the profile's
  provider_models_cache.json (this command fetches no model lists itself). The
  cost/data-policy selection warning is Hermes' own and may consult provider
  pricing metadata. Credentials are not displayed or newly stored by this command.
- The interactive picker writes only after confirmation; the explicit set command
  writes on invocation. Cancel, skip, or EOF is "No change." The profile's existing
  delegation.fallback_providers chain stays in force untouched, and this
  command only counts the configured entries in every notice (show, the pick
  summary, and set), never showing providers, URLs, or keys inside that chain.
"""

from pathlib import Path

_RULES_PATH = Path(__file__).resolve().parent / "SUBAGENT.md"


def _report_rules(session_info):
    if session_info.get("platform") != "subagent":
        return ""
    return _RULES_PATH.read_text(encoding="utf-8")


# ------------------------------------------------------------------ view

def _delegation_section(config):
    section = config.get("delegation")
    return section if isinstance(section, dict) else {}


def _effort_display(raw) -> str:
    """Stored delegation.reasoning_effort as display text ("" = inherit parent)."""
    if raw is None or raw == "":
        return ""
    if raw is False or str(raw).strip().lower() in {"none", "false", "disabled"}:
        return "none"
    return str(raw)


def _cached_model_ids(provider_id: str) -> list:
    """Model ids from the profile's provider model cache (disk read, never a fetch)."""
    from hermes_cli.models import _load_provider_models_cache

    entry = _load_provider_models_cache().get(provider_id)
    models = entry.get("models") if isinstance(entry, dict) else None
    return [str(model) for model in models] if isinstance(models, list) else []


def _provider_rows(config):
    """Selectable providers: configured entries first, then Hermes' canonical list.

    The configured view is Hermes' own (get_compatible_custom_providers), so the
    v12+ 'providers:' section and legacy 'custom_providers' both appear; native
    providers (openai-codex, openrouter, ...) come from _PROVIDER_LABELS. Model
    ids use locally known data only: config.yaml declarations and the profile's
    provider_models_cache.json; an unknown list means "type the model id".
    """
    from hermes_cli.config import get_compatible_custom_providers
    from hermes_cli.models import _PROVIDER_LABELS

    rows, seen = [], set()
    for entry in get_compatible_custom_providers(config):
        provider_id = str(entry.get("provider_key") or "").strip()
        if not provider_id or provider_id in seen:
            continue
        models = entry.get("models")
        model_ids = [str(model) for model in models] if isinstance(models, (dict, list)) else []
        declared = str(entry.get("model") or "").strip()
        if declared and declared not in model_ids:
            model_ids.append(declared)
        rows.append({"id": provider_id, "name": str(entry.get("name") or provider_id),
                     "models": model_ids or _cached_model_ids(provider_id),
                     "base_url": str(entry.get("base_url") or "").strip()})
        seen.add(provider_id)
    for slug in sorted(_PROVIDER_LABELS):
        if slug in seen or slug == "custom":
            continue
        rows.append({"id": slug, "name": str(_PROVIDER_LABELS[slug]),
                     "models": _cached_model_ids(slug), "base_url": ""})
        seen.add(slug)
    return rows


def _configured_ids(config):
    return {str(key) for key in (config.get("providers") or {}) if isinstance(config.get("providers"), dict)}


def _print_pin(config) -> None:
    delegation = _delegation_section(config)
    provider = str(delegation.get("provider") or "")
    model = str(delegation.get("model") or "")
    effort = _effort_display(delegation.get("reasoning_effort"))
    if not provider and not model:
        print("  Subagent model:   inherits the parent model (no pin)")
        return
    print(f"  Subagent provider:  {provider or '(unset)'}")
    print(f"  Subagent model:     {model or '(unset)'}")
    print(f"  Subagent effort:    {effort or '(inherit parent level)'}")


def _route_conflict(config):
    """Why writing delegation.provider/model would be ineffective here, or None.

    Refusal is deliberate: silently writing keys the active route ignores, or
    re-pointing the provider while a fixed endpoint stays pinned, has produced
    misrouted children; manual selection states the conflict instead.
    """
    delegation = _delegation_section(config)
    backend = str(delegation.get("backend") or "default").strip()
    if backend != "default":
        return ("delegation.backend is '" + backend + "': provider/model keys in the delegation "
                "section are read only by the default backend. Configure that backend's own routes, "
                "or set delegation.backend to default yourself (hermes config set delegation.backend default).")
    if str(delegation.get("base_url") or "").strip():
        return ("delegation.base_url pins a fixed endpoint, so changing provider/model here would keep "
                "that endpoint and can misroute. Remove the endpoint pin yourself "
                "(hermes config unset delegation.base_url) if this command should manage the route.")
    return None


def _fallback_notice(config) -> None:
    """Count-only reminder that the profile's existing fallback chain stays in force."""
    fallbacks = _delegation_section(config).get("fallback_providers")
    if isinstance(fallbacks, list) and fallbacks:
        print("  Fallback chain:     %d configured entr%s; this command keeps it in force and never "
              "shows or changes it (manage via hermes config)"
              % (len(fallbacks), "y" if len(fallbacks) == 1 else "ies"))


def _guard_confirmed(model_id: str, provider_id: str, base_url: str) -> bool:
    """Hermes' own model-selection guard (cost / data-policy ...); False means do not write."""
    from hermes_cli.auth_model_picker import _confirm_selection_guards

    return _confirm_selection_guards(model_id, provider=provider_id, base_url=base_url)


# --------------------------------------------------------------- actions

def _show(_: object) -> None:
    from hermes_cli.config import load_config_readonly

    config = load_config_readonly() or {}
    model_cfg = config.get("model") if isinstance(config.get("model"), dict) else {}
    print()
    print("  Delegation backend: %s" % (str(_delegation_section(config).get("backend") or "default")))
    _print_pin(config)
    _fallback_notice(config)
    main_model = str(model_cfg.get("default") or "(not set)")
    print(f"  Main model:         {main_model} (unchanged by this command)")
    print()
    configured = _configured_ids(config)
    rows = _provider_rows(config)
    print("  Configured providers (models declared in config.yaml):")
    for row in rows:
        if row["id"] in configured:
            print(f"    - {row['id']}: {', '.join(row['models']) or '(none declared)'}")
    other = [row["id"] for row in rows if row["id"] not in configured]
    if other:
        print("  Other Hermes providers (model list comes from the picker cache; unknown = type the id):")
        print("    " + ", ".join(other))
    print()
    conflict = _route_conflict(config)
    if conflict:
        print(f"  Route conflict: {conflict}")
        print()
    print("  Select manually:  hermes subagent-model pick")
    print("  Or with the built-in config commands (what this plugin writes through):")
    print("    hermes config set delegation.model <id>")
    print("    hermes config set delegation.provider <id>")
    print("    hermes config set delegation.reasoning_effort <level>")


def _apply_pin(provider_id: str, model: str, effort):
    """Persist one explicit selection as a narrow partial write.

    Returns the refusal reason, or None once written. The picker can sit open for minutes, so
    the live config is re-read here (load_config() reloads when the file signature changed) and
    re-checked for a route conflict instead of trusting the copy the menus were built from; the
    write then carries ONLY the selected delegation keys with merge_existing=True, which
    deep-merges the on-disk config under them under Hermes' config lock.
    """
    from hermes_cli import config as config_mod

    selected = {"provider": provider_id, "model": model}
    if effort is not None:
        selected["reasoning_effort"] = False if effort == "none" else effort
    with config_mod._CONFIG_LOCK:
        conflict = _route_conflict(config_mod.load_config() or {})
        if conflict:
            return conflict
        config_mod.save_config({"delegation": selected},
                               preserve_keys={("delegation", key) for key in selected},
                               merge_existing=True)
    suffix = f" (reasoning effort: {effort})" if effort is not None else " (reasoning effort: unchanged)"
    print(f"Delegation route set: {provider_id} : {model}{suffix}. "
          "The shared subagent reporting rules are unchanged.")
    return None


def _pick(_: object) -> None:
    from hermes_cli.auth_model_picker import _prompt_model_selection
    from hermes_cli.config import load_config
    from hermes_cli.main_provider_setup import _prompt_provider_choice, _prompt_reasoning_effort_selection
    from hermes_constants import VALID_REASONING_EFFORTS

    config = load_config()
    conflict = _route_conflict(config)
    if conflict:
        print("Refusing to change the subagent model: " + conflict)
        raise SystemExit(1)

    delegation = _delegation_section(config)
    current_provider = str(delegation.get("provider") or "")
    current_model = str(delegation.get("model") or "")
    current_effort = _effort_display(delegation.get("reasoning_effort"))

    rows = _provider_rows(config)
    labels = ["No change (keep the current subagent model)"] + [f"{row['id']} — {row['name']}" for row in rows]
    default_idx = next((i + 1 for i, row in enumerate(rows) if row["id"] == current_provider), 0)
    choice = _prompt_provider_choice(labels, default=default_idx, title="Select subagent provider:")
    if choice is None or choice == 0:
        print("No change.")
        return
    provider = rows[choice - 1]

    model = _prompt_model_selection(
        provider["models"],
        current_model=current_model if provider["id"] == current_provider else "",
        title=f"Select subagent model ({provider['id']}):",
        confirm_provider=provider["id"],
        confirm_base_url=provider["base_url"],
    )
    if model is None:
        print("No change (a pin needs both a provider and a model).")
        return

    effort = _prompt_reasoning_effort_selection(VALID_REASONING_EFFORTS, current_effort=current_effort)

    print()
    _fallback_notice(config)
    print("  Subagent model will become:")
    print(f"    provider:         {provider['id']}")
    print(f"    model:            {model}")
    print(f"    reasoning effort: {effort if effort is not None else '(keep current)'}")
    try:
        answer = input("\n  Apply? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer not in {"y", "yes"}:
        print("No change.")
        return
    reason = _apply_pin(provider["id"], model, effort)
    if reason:
        print("Refusing to change the subagent model: " + reason)
        raise SystemExit(1)


def _set_manual(args) -> None:
    from hermes_cli.config import load_config
    from hermes_constants import parse_reasoning_effort

    effort = args.effort
    if effort is not None and parse_reasoning_effort(effort) is None:
        print(f"Unknown reasoning effort: {effort!r} (use minimal|low|medium|high|xhigh|max|ultra|none).")
        raise SystemExit(1)

    config = load_config()
    conflict = _route_conflict(config)
    if conflict:
        print("Refusing to change the subagent model: " + conflict)
        raise SystemExit(1)

    if args.provider not in _configured_ids(config):
        print(f"Note: '{args.provider}' has no configured provider section in config.yaml; pinning it "
              "anyway (credentials stay configured by Hermes). Configured: "
              f"{', '.join(sorted(_configured_ids(config))) or 'none'}")

    base_url = next((row["base_url"] for row in _provider_rows(config) if row["id"] == args.provider), "")
    if not _guard_confirmed(args.model, args.provider, base_url):
        print("No change (the selection guard was not confirmed).")
        raise SystemExit(1)
    _fallback_notice(config)
    reason = _apply_pin(args.provider, args.model, None if effort is None else effort.lower())
    if reason:
        print("Refusing to change the subagent model: " + reason)
        raise SystemExit(1)


# ----------------------------------------------------------------- wiring

def _setup_cli(parser) -> None:
    sub = parser.add_subparsers(dest="subaction")
    sub.add_parser("show", help="print the current subagent (delegation) model pin")
    sub.add_parser("pick", help="interactively select provider, model, and reasoning effort")
    set_parser = sub.add_parser("set", help="pin provider and model manually (one atomic write)")
    set_parser.add_argument("provider", help="provider id (e.g. omlx or openai-codex)")
    set_parser.add_argument("model", help="model id")
    set_parser.add_argument("--effort", default=None,
                            help="minimal|low|medium|high|xhigh|max|ultra|none (omit to keep current)")


def _handle_cli(args) -> None:
    action = getattr(args, "subaction", None) or "show"
    if action == "pick":
        _pick(args)
    elif action == "set":
        _set_manual(args)
    else:
        _show(args)


def register(ctx):
    ctx.register_system_prompt_section("global-subagent-rules.report-rules", _report_rules)
    ctx.register_cli_command(
        "subagent-model",
        help="View or manually select the delegation (subagent) model",
        setup_fn=_setup_cli,
        handler_fn=_handle_cli,
        description=(
            "Manual view/pick/persist for the delegation model. Writes delegation.provider/model/"
            "reasoning_effort in one partial save_config (merge_existing) after re-reading the live config; "
            "refuses to write under a non-default delegation.backend "
            "or a pinned delegation.base_url; never changes the main model or displays credentials; "
            "an existing delegation.fallback_providers chain stays in force and is only counted."
        ),
    )
