"""`provider/base.py` 的 **签名级** 一致性用例（控制者自写，Task 4.1）。

## 本文件补的是哪个洞（这是它存在的唯一理由）

`base.py` 有 100% 的**行覆盖**——但那是假的安全感：三个 Protocol 的方法体全是 `...`，
任何一次导入都会把这 26 行全部"覆盖"到，而**签名是否一致一个字都没验**。
`@runtime_checkable` 的 `isinstance` 也只检查**成员是否存在**，不检查签名、不看返回类型、
不看参数名与参数种类（keyword-only / 默认值）。

于是存在一条完全静默的退化路径：

    service 按 Protocol 调 `await ocr.recognize(image_key=…, doc_type=…, timeout_s=…)`，
    而实现写成 `recognize(self, image, doc, timeout)` ——
    `isinstance` 为真、行覆盖率 100%、全部现有用例绿，**运行到真实调用那一刻才 TypeError**。

本文用 `inspect.signature ==` 把「结构子类型」做成**逐参数可执行判据**：
参数名、参数种类（POSITIONAL_OR_KEYWORD / KEYWORD_ONLY）、顺序、默认值、注解**全等**。

## 判别力自证的两次修正（评审 B2，如实留档）

**初版写法是错的**：它只在**合成类**上比 `signature != signature`，
从未让真正的一致性判据参与。P 阶段独立评审用变异测试证实：
把判据弱化成「参数个数比较」**同时**在 `deepseek.py` 制造真签名漂移（删掉 `*`），
**全量 1088 条仍全绿**，自证用例自己也绿——判据被弱化了，而"证明判据有效"的那条用例
没有察觉。这正是本任务要防的假绿形态，却出现在防它的用例里。

**修法三条**（缺任何一条都会让 B2 复现）：

1. 判据抽成具名函数 `assert_signature_conforms`，自证用例直接调用**它**（不复制逻辑）；
2. 把漂移实现 `_DriftedTextProvider` **挂进真实矩阵**——判据一旦被弱化，
   参数化路径那条用例立刻变红；
3. 另加 `test_conformance_assertion_rejects_a_drifted_implementation` 直接验证判据函数
   对真实漂移会抛错，并**先断言这个载体确实是漂移**（防载体失效后自证变成空转）。
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from aicore.provider import cloud_ocr, cloud_vision, deepseek, mock
from aicore.provider.base import OcrProvider, TextProvider, VisionProvider
from aicore.provider.results import ProviderResult


class _DriftedTextProvider:
    """**故意漂移**的文本通道：丢了 `*`，参数从 keyword-only 退化成可正位置传。

    它就是评审在 `deepseek.py:134` 人为制造的那种漂移的可执行副本。
    挂进矩阵后，它必须**永远**让一致性判据失败——故矩阵用例对它取反断言。
    """

    name = "drifted"
    model_version = "drifted-v1"
    prompt_version = "drifted-p1"

    async def complete(
        self,
        prompt: str,  # 少了 `*`
        payload: dict[str, Any],
        timeout_s: float,
    ) -> ProviderResult:
        raise NotImplementedError

    def model_meta(self) -> dict[str, Any]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 被测对象矩阵：(Protocol, 方法名, 实现类)
#
# 新增通道时**必须**往这里加一行——这是刻意的：让「加了通道」这件事
# 在用例里有可见的落点，而不是靠人记得同步一份隐藏清单。
# 最后一行是判别力载体，不是真实实现（见 `test_matrix_covers_every_channel_file`）。
# ---------------------------------------------------------------------------
CONFORMANCE_MATRIX: tuple[tuple[type, str, type], ...] = (
    (TextProvider, "complete", mock.MockTextProvider),
    (VisionProvider, "analyze", mock.MockVisionProvider),
    (OcrProvider, "recognize", mock.MockOcrProvider),
    (TextProvider, "complete", deepseek.DeepSeekTextProvider),
    (VisionProvider, "analyze", cloud_vision.CloudVisionProvider),
    (OcrProvider, "recognize", cloud_ocr.CloudOcrProvider),
    (TextProvider, "complete", _DriftedTextProvider),
)

_IDS = [f"{cls.__name__}.{meth}" for _, meth, cls in CONFORMANCE_MATRIX]


def _protocol_callable(protocol: type, method: str) -> Any:
    """取 Protocol 上的方法对象（`getattr` 拿到的是函数，不是绑定方法）。"""
    return getattr(protocol, method)


def assert_signature_conforms(protocol: type, method: str, impl: type) -> None:
    """一致性判据本体。**抽成具名函数**，好让判别力自证能让**它**跑在漂移实现上。"""
    expected = inspect.signature(_protocol_callable(protocol, method))
    actual = inspect.signature(getattr(impl, method))

    assert actual == expected, (
        f"{impl.__name__}.{method} 与 {protocol.__name__} 的签名不一致。\n"
        f"  契约（{protocol.__name__}）：{expected}\n"
        f"  实现（{impl.__name__}）：{actual}\n"
        f"  差异参数：{set(expected.parameters) ^ set(actual.parameters)}"
    )


@pytest.mark.parametrize(("protocol", "method", "impl"), CONFORMANCE_MATRIX, ids=_IDS)
def test_implementation_signature_equals_protocol_signature(
    protocol: type, method: str, impl: type
) -> None:
    """实现方法的 `inspect.signature` 必须与 Protocol **完全相等**。

    「完全相等」在这里的具体含义（`Signature.__eq__` 的语义）：

    - 参数**名字**相同；
    - 参数**顺序**相同；
    - 参数**种类**相同（尤其 `*` 之后的 keyword-only 标记不能丢）；
    - **默认值**相同；
    - **注解**相同（`from __future__ import annotations` 下都是字符串，两边同源故可逐字比）。

    为什么用 `==` 而不是「实现是 Protocol 的宽松超集」：
    `service` 是按 Protocol 签名的**唯一**调用形态写代码的，
    一个「更宽松」的实现并不能让调用方多写一种形态，却会让两边悄悄分叉。

    **对矩阵里的漂移载体取反断言**：它 MUST 让判据失败。这样「判据被弱化」这件事
    会在这条参数化用例上立刻变红（评审 B2 的假绿正是判据被弱化而无人察觉）。
    """
    if impl is _DriftedTextProvider:
        with pytest.raises(AssertionError, match="签名不一致"):
            assert_signature_conforms(protocol, method, impl)
        return

    assert_signature_conforms(protocol, method, impl)


@pytest.mark.parametrize(("protocol", "method", "impl"), CONFORMANCE_MATRIX, ids=_IDS)
def test_implementation_method_is_async(protocol: type, method: str, impl: type) -> None:
    """方法必须是**协程函数**。

    依据：`base.py` 的三个方法都声明为 `async def`，`service` 侧按 `await` 调用。
    实现若写成同步函数，`await` 会 `TypeError: object NoneType can't be used in
    'await' expression`——而这条错误**在启动期、导入期、isinstance 期都不会暴露**。
    """
    if impl is _DriftedTextProvider:
        # 载体本身就是 async，这条对它无判别意义；跳过而不是伪装成"验过了"。
        pytest.skip("判别力载体：它的用途是签名漂移，不是协程性")
    assert inspect.iscoroutinefunction(getattr(impl, method)), (
        f"{impl.__name__}.{method} 不是协程函数：base.py 的契约是 async def"
    )


@pytest.mark.parametrize(("protocol", "method", "impl"), CONFORMANCE_MATRIX, ids=_IDS)
def test_implementation_declares_the_three_identity_members(
    protocol: type, method: str, impl: type
) -> None:
    """`name` / `model_version` / `prompt_version` 三个数据成员必须存在**且是字符串**。

    `runtime_checkable` 只检查存在性：`model_version = 1` 也能通过 `isinstance`。
    而这三个值会写进 `ai_task.model_meta`（`er.md` §6.1）并随任务查询返回，
    类型错了会在**落库或序列化那一刻**才炸。
    """
    assert isinstance(impl, type), f"{impl} 不是类"
    for member in ("name", "model_version", "prompt_version"):
        # 从**类**上取：这三个是类属性（`__init__` 里不重新赋值），
        # 取不到说明实现根本没声明它，`runtime_checkable` 也会因此判 False。
        value = getattr(impl, member, None)
        assert isinstance(value, str) and value, (
            f"{impl.__name__}.{member} 不是非空字符串（实际 {value!r}）："
            f"该值要落 ai_task.model_meta，类型错会在写库时才炸"
        )


@pytest.mark.parametrize(("protocol", "method", "impl"), CONFORMANCE_MATRIX, ids=_IDS)
def test_implementation_is_a_runtime_checkable_instance(
    protocol: type, method: str, impl: type
) -> None:
    """`isinstance(impl, protocol)` 为真。

    **这条只证明成员存在**（见模块 docstring），故它是上面三条的补充而非替代。
    保留它的价值：它是 `@runtime_checkable` 语义的**显式可核形式**——
    否则「Protocol 是结构子类型」这句话在仓库里没有任何可执行证据。

    **传类而不是实例**：对含**数据成员**的 Protocol，`runtime_checkable` 的
    `isinstance` 检查的是 `hasattr`，而类属性在**类**上就能取到，
    故 `isinstance(SomeProvider, TextProvider)` 成立。早期版本这里构造实例、
    对需要构造参数的真实通道 `pytest.skip`——那是**没有理由的跳过**：
    它会让真实通道恰好躲开这条检查，而真实通道才是最需要被检查的一侧。
    """
    assert isinstance(impl, protocol), (
        f"{impl.__name__} 不满足 {protocol.__name__} 的结构契约"
        f"（缺成员：{sorted(set(dir(protocol)) - set(dir(impl)))}）"
    )


def test_conformance_assertion_rejects_a_drifted_implementation() -> None:
    """**判别力自证**：`assert_signature_conforms` 对真实漂移 MUST 失败。

    与矩阵里那条取反断言的分工：

    - 本条直接调用判据函数，断言它抛 `AssertionError`（证明判据本身会红）；
    - 矩阵那条证明**它在参数化路径上真的被调用**（防"判据没被接上"）。

    少了任何一条，评审 B2 的假绿都会复现：判据被弱化 / 判据没被调用，
    两种失效各自都能让全量保持全绿。
    """
    # 先确认这个载体**确实是**漂移（否则断言方向就错了，用例会变成空转）
    expected = inspect.signature(TextProvider.complete)
    drifted = inspect.signature(_DriftedTextProvider.complete)
    assert drifted != expected, (
        f"_DriftedTextProvider 不再漂移（{drifted} == {expected}）："
        f"本自证用例已失去意义，请重新构造一个真的不一致的实现"
    )

    with pytest.raises(AssertionError, match="签名不一致"):
        assert_signature_conforms(TextProvider, "complete", _DriftedTextProvider)


def test_matrix_covers_every_channel_file() -> None:
    """矩阵必须覆盖 `provider/` 下**每一个**真实通道实现类。

    为什么要有这条：上面几条都是 `parametrize`，**删掉矩阵里的一行就等于静默少验一个通道**，
    而 pytest 不会因此变红。本用例把「矩阵是否完整」变成一条独立断言：
    它把矩阵里的**真实实现**类集合与显式列出的期望集合比对
    （漂移载体是自证工具，不属真实实现，故从集合比对里排除）。
    """
    discovered = {cls for _, _, cls in CONFORMANCE_MATRIX if cls is not _DriftedTextProvider}
    expected = {
        mock.MockTextProvider,
        mock.MockVisionProvider,
        mock.MockOcrProvider,
        deepseek.DeepSeekTextProvider,
        cloud_vision.CloudVisionProvider,
        cloud_ocr.CloudOcrProvider,
    }
    assert discovered == expected, (
        f"矩阵少验了：{sorted(c.__name__ for c in expected - discovered)}；"
        f"矩阵多出：{sorted(c.__name__ for c in discovered - expected)}"
    )
    assert len(CONFORMANCE_MATRIX) == len(expected) + 1, (
        "矩阵长度应为「真实实现数 + 1 条漂移载体」：漂移载体被删掉就没人守判据了"
    )


# ---------------------------------------------------------------------------
# 判别力自证（合成类版本）：覆盖判据的各个失效维度
#
# 上面那条用的是**真实漂移**（丢 `*`）。下面这条在同一用例里把判据的每一个
# 失效维度都摆出来，好处是「判据在哪个维度上失效」一眼可见。
# ---------------------------------------------------------------------------
def test_signature_equality_is_discriminating() -> None:
    """证明「签名相等」这条判据在**每个维度**上都会因不一致而变红。"""

    class _Contract:
        async def run(self, *, alpha: int, beta: str, timeout_s: float) -> None: ...

    class _DifferentName:
        async def run(self, *, alpha: int, gamma: str, timeout_s: float) -> None: ...

    class _DifferentKind:
        # 丢了 `*`：参数从 keyword-only 退化成正位置可传
        async def run(self, alpha: int, beta: str, timeout_s: float) -> None: ...

    class _MissingParameter:
        async def run(self, *, alpha: int, timeout_s: float) -> None: ...

    class _ExtraParameter:
        async def run(self, *, alpha: int, beta: str, timeout_s: float, extra: int = 0) -> None: ...

    class _SyncInsteadOfAsync:
        def run(self, *, alpha: int, beta: str, timeout_s: float) -> None: ...

    class _DifferentDefault:
        async def run(self, *, alpha: int, beta: str, timeout_s: float = 1.0) -> None: ...

    class _Conforming:
        async def run(self, *, alpha: int, beta: str, timeout_s: float) -> None: ...

    expected = inspect.signature(_Contract.run)
    drifted = {
        "_DifferentName": _DifferentName,
        "_DifferentKind": _DifferentKind,
        "_MissingParameter": _MissingParameter,
        "_ExtraParameter": _ExtraParameter,
        "_DifferentDefault": _DifferentDefault,
    }

    # 对照组：唯一合规的那个**必须**判为相等，否则判据严到会误伤正确代码，
    # 那样它就不再是「契约守卫」而是「永远红的噪声」，一样没有价值。
    assert inspect.signature(_Conforming.run) == expected, (
        "合规实现被判为不等：判据过严，会误伤正确代码"
    )

    for name, cls in drifted.items():
        assert inspect.signature(cls.run) != expected, (
            f"{name} 的签名与契约不同，判据却认为相等——**断言已退化成恒真**"
        )

    assert not inspect.iscoroutinefunction(_SyncInsteadOfAsync.run), (
        "同步实现被 iscoroutinefunction 判为协程：协程性判据已失效"
    )
