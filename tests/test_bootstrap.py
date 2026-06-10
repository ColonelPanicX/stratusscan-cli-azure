import subprocess
import sys

import bootstrap
import utils


def test_ensure_dependencies_installs_pyproject_dependencies_when_module_missing(monkeypatch):
    calls = []
    exec_calls = []

    monkeypatch.setattr(
        bootstrap,
        "_is_missing",
        lambda module: module == "azure.mgmt.resource.subscriptions",
    )
    monkeypatch.setattr(
        bootstrap,
        "_read_pyproject_dependencies",
        lambda: ["azure-mgmt-resource>=23.0.0,<25.0.0"],
    )
    monkeypatch.setattr(subprocess, "run", lambda cmd, check: calls.append((cmd, check)))
    monkeypatch.delenv(bootstrap._ATTEMPTED_ENV, raising=False)
    monkeypatch.setattr(bootstrap.os, "execv", lambda executable, args: exec_calls.append((executable, args)))

    bootstrap.ensure_dependencies()

    assert calls == [
        ([sys.executable, "-m", "pip", "install", "azure-mgmt-resource>=23.0.0,<25.0.0"], True)
    ]
    assert exec_calls == [(sys.executable, [sys.executable, *sys.argv])]


def test_ensure_dependencies_skips_pip_when_required_modules_exist(monkeypatch):
    monkeypatch.setattr(bootstrap, "_is_missing", lambda module: False)

    def fail_run(*args, **kwargs):
        raise AssertionError("pip should not run when dependencies are present")

    monkeypatch.setattr(subprocess, "run", fail_run)

    bootstrap.ensure_dependencies()


def test_ensure_dependencies_does_not_loop_after_install_attempt(monkeypatch):
    monkeypatch.setattr(bootstrap, "_is_missing", lambda module: True)
    monkeypatch.setenv(bootstrap._ATTEMPTED_ENV, "1")

    def fail_run(*args, **kwargs):
        raise AssertionError("pip should not run after bootstrap was already attempted")

    monkeypatch.setattr(subprocess, "run", fail_run)

    bootstrap.ensure_dependencies()


def test_resource_dependency_is_capped_below_split_release():
    deps = bootstrap._read_pyproject_dependencies()

    assert "azure-mgmt-resource>=23.0.0,<25.0.0" in deps


def test_resource_clients_use_stable_submodule_paths():
    assert utils._CLIENT_MAP["subscription"] == (
        "azure.mgmt.resource.subscriptions",
        "SubscriptionClient",
        False,
    )
    assert utils._CLIENT_MAP["resource"] == (
        "azure.mgmt.resource.resources",
        "ResourceManagementClient",
        True,
    )


def test_government_clients_use_government_arm_scope(monkeypatch):
    captured = {}

    class Client:
        def __init__(self, credential, **kwargs):
            captured["credential"] = credential
            captured["kwargs"] = kwargs

    monkeypatch.setitem(
        utils._CLIENT_MAP,
        "subscription",
        ("tests.fake_module", "Client", False),
    )
    monkeypatch.setattr(utils, "_get_credential", lambda: "credential")
    monkeypatch.setattr(utils, "detect_environment", lambda: "government")

    def fake_import_module(module_path):
        assert module_path == "tests.fake_module"

        class Module:
            pass

        Module.Client = Client
        return Module

    monkeypatch.setattr("importlib.import_module", fake_import_module)

    utils.get_azure_client("subscription")

    assert captured["credential"] == "credential"
    assert captured["kwargs"]["base_url"] == "https://management.usgovcloudapi.net"
    assert captured["kwargs"]["credential_scopes"] == [
        "https://management.usgovcloudapi.net/.default"
    ]


def test_government_credential_rewrites_public_arm_scope():
    captured = {}

    class Credential:
        def get_token(self, *scopes, **kwargs):
            captured["scopes"] = scopes
            captured["kwargs"] = kwargs
            return "token"

    credential = utils._GovernmentCredential(Credential())

    token = credential.get_token("https://management.azure.com/.default", tenant_id="tenant")

    assert token == "token"
    assert captured["scopes"] == ("https://management.usgovcloudapi.net/.default",)
    assert captured["kwargs"] == {"tenant_id": "tenant"}
