"""分层依赖规则检查。

对应 design.md「依赖方向规则」的 6 条禁止项，其中规则 1~4 由 import-linter 契约承载，
规则 5、6 见 tests/structural/test_source_guards.py。

阳性/阴性双向验证：契约在干净代码上必须通过；**四条契约各自**都要有「注入违规 → 变红」的
阴性证据，外加一条「注入放行导入 → 仍然通过」的正例，守住 ignore_imports 写错即静默失效的风险。
四条契约的间接导入取舍见 .importlinter 内逐条注释。

缓存：所有 lint 调用都传 cache_dir=None（import-linter 2.15 支持，None 即关缓存），
避免在仓库内留下 .import_linter_cache/ 残留。
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG = PROJECT_ROOT / ".importlinter"
SRC = PROJECT_ROOT / "src" / "aicore"
PROVIDER_INIT = SRC / "provider" / "__init__.py"


class Probe(NamedTuple):
    """一条契约的阴性探针：把 forbidden 导入放进 source 包内，契约必须变红。"""

    contract_id: str
    rule: str
    probe_relpath: str
    probe_source: str


# 四个探针各自只制造一处违规，其余三条契约必须仍为 KEPT（已逐条实测）。
PROBES: tuple[Probe, ...] = (
    Probe(
        contract_id="api-no-repo-provider",
        rule="禁止项 1：api 不得直接依赖 repository / provider",
        probe_relpath="api/routes_probe.py",
        probe_source="from aicore.repository import task_repo\n",
    ),
    Probe(
        contract_id="service-provider-impl",
        rule="禁止项 2：service 不得依赖具体通道实现",
        probe_relpath="service/svc_probe.py",
        probe_source="from aicore.provider import mock\n",
    ),
    Probe(
        contract_id="no-reverse-dependency",
        rule="禁止项 3：repository / provider / port 不得反向依赖 service",
        probe_relpath="repository/repo_probe.py",
        probe_source="from aicore.service import desensitize\n",
    ),
    Probe(
        contract_id="core-independent",
        rule="禁止项 4：core 不得依赖任何业务层",
        probe_relpath="core/core_probe.py",
        probe_source="from aicore.api import health\n",
    ),
)


@pytest.fixture(scope="module")
def lint() -> Callable[..., bool]:
    # 必须先 import importlinter.api：它调用 configuration.configure()，
    # 注册 USER_OPTION_READERS；只 import use_cases 会报 'USER_OPTION_READERS' KeyError。
    import importlinter.api  # noqa: F401
    from importlinter.application.use_cases import lint_imports

    return lint_imports


@contextmanager
def probe_files(files: dict[Path, str]) -> Iterator[None]:
    """临时写入探针文件，退出时无条件还原（含异常路径）。

    探针写在真实源码树里——import-linter 只认磁盘上的包结构，无法喂内存源码。
    文件名为 *_probe.py，不会与真实模块重名；退出时逐个删除，
    被覆盖的既有文件按内容还原，故注入不会留下改动（git diff 为空是关键证据）。
    """
    backup = {path: path.read_text(encoding="utf-8") for path in files if path.exists()}
    try:
        for path, content in files.items():
            path.write_text(content, encoding="utf-8")
        importlib.invalidate_caches()
        yield
    finally:
        for path in files:
            if path in backup:
                path.write_text(backup[path], encoding="utf-8")
            else:
                path.unlink(missing_ok=True)
        importlib.invalidate_caches()


def lint_once(
    lint: Callable[..., bool],
    contract_id: str | None = None,
    config: Path | None = None,
) -> bool:
    """跑一次 lint；contract_id 非空时只判该契约，避免其余契约的噪声。

    缓存一律关闭（cache_dir=None），故仓库内不会出现 .import_linter_cache/。
    """
    kwargs: dict[str, object] = {"no_logo": True, "cache_dir": None}
    if contract_id is not None:
        kwargs["limit_to_contracts"] = (contract_id,)
    return lint(config_filename=str(config or CONFIG), **kwargs)


def test_layering_contracts_pass(lint: Callable[..., bool]) -> None:
    """干净代码上，全部分层契约必须通过，且不得有未匹配的放行表达式。"""
    assert lint_once(lint) is True


@pytest.mark.parametrize("probe", PROBES, ids=lambda p: p.contract_id)
def test_contract_goes_red_on_violation(lint: Callable[..., bool], probe: Probe) -> None:
    """阴性用例：每条契约都要有一条「注入违规 → 变红」的证据。"""
    target = SRC / probe.probe_relpath
    with probe_files({target: probe.probe_source}):
        # 先单判该契约：失败信息直接点名是哪条契约没响，不会与其它契约混淆。
        assert lint_once(lint, probe.contract_id) is False, (
            f"{probe.contract_id} 未响：{probe.rule} 的注入探针 {probe.probe_relpath} 没让契约变红"
        )
        # 再全量判一次：确认注入的违规没有顺带打翻其它契约（只由该契约负责）。
        assert lint_once(lint) is False


def test_allowed_provider_base_import_is_kept(lint: Callable[..., bool]) -> None:
    """正例（放行回归）：service 导入 provider.base 合法，契约必须保持 KEPT。

    守的是 ignore_imports 的 `aicore.service.** -> aicore.provider.base`：
    它一旦写错（如退回成不匹配任何子模块的 `aicore.service`），本条会立刻变红。
    """
    target = SRC / "service" / "svc_probe.py"
    with probe_files({target: "from aicore.provider import base\n"}):
        assert lint_once(lint, "service-provider-impl") is True
        assert lint_once(lint) is True


def test_ignore_imports_still_needed_for_provider_base(lint: Callable[..., bool]) -> None:
    """反证：把 ignore_imports 从配置里抽掉，同一条合法导入必须变红。

    没有这一步，「正例通过」既可能是放行生效，也可能是契约根本没在看——
    抽掉放行后变红，才证明那行 ignore_imports 真的在承载这条合法路径。
    变异配置写到仓库内的临时文件名下，finally 无条件删除（沙箱内系统临时目录不可写）。
    """
    config_text = CONFIG.read_text(encoding="utf-8")
    mutated = config_text.replace("    aicore.service.** -> aicore.provider.base\n", "", 1)
    assert mutated != config_text, "变异失败：配置里找不到 service -> provider.base 的放行行"

    target = SRC / "service" / "svc_probe.py"
    with probe_files({target: "from aicore.provider import base\n"}):
        mutated_config = PROJECT_ROOT / ".importlinter_nonexistent"
        assert not mutated_config.exists(), "变异配置文件不该存在"
        try:
            mutated_config.write_text(mutated, encoding="utf-8")
            importlib.invalidate_caches()
            assert lint_once(lint, "service-provider-impl", config=mutated_config) is False
        finally:
            mutated_config.unlink(missing_ok=True)


def test_provider_facade_reexport_is_forbidden(lint: Callable[..., bool]) -> None:
    """阴性用例：provider 门面再导出相邻层模块时，`import aicore.provider` 必须被抓。

    这是把 aicore.provider 整包写进 forbidden_modules 的独立理由：
    若 provider/__init__.py 只再导出 aicore.provider.* 之外的符号（如 aicore.port.x），
    只列 5 个具体实现模块的配置会漏掉 service -> aicore.provider -> aicore.port.x 这条链。
    """
    facade_export = SRC / "port" / "facade_probe.py"
    with probe_files(
        {
            facade_export: '"""探针：被 provider 门面再导出的相邻层模块。"""\n',
            PROVIDER_INIT: (
                PROVIDER_INIT.read_text(encoding="utf-8")
                + "from aicore.port.facade_probe import *  # noqa: F403\n"
            ),
            SRC / "service" / "svc_probe.py": "import aicore.provider\n",
        }
    ):
        assert lint_once(lint, "service-provider-impl") is False
