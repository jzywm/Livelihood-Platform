package com.msz.acc.domain.service;

import com.msz.acc.domain.model.RealNameLevel;
import com.msz.acc.domain.model.RealNameStatus;
import com.msz.acc.domain.support.AccBusinessException;

/**
 * 实名状态机。
 * 口径：er.md §3 状态机 + PDD §5.1.2 + test-plan.md UT-A01/A02/A03/A09。
 * 非法迁移抛 AccBusinessException(3007，状态不允许该操作)。
 */
public final class RealnameStatusMachine {

    /** UT-A01：发起实名，UNREALNAMED → REALNAMING。 */
    public RealNameStatus start(RealNameStatus current) {
        if (current != RealNameStatus.UNREALNAMED) {
            throw new AccBusinessException(3007, "当前实名状态不允许发起实名");
        }
        return RealNameStatus.REALNAMING;
    }

    /** UT-A01：第三方回调实名通过，REALNAMING → REALNAMED。 */
    public RealNameStatus onCallbackPass(RealNameStatus current) {
        if (current != RealNameStatus.REALNAMING) {
            throw new AccBusinessException(3007, "当前实名状态不允许置为已实名");
        }
        return RealNameStatus.REALNAMED;
    }

    /** UT-A02：第三方不可用（红线 R-02 不降级），REALNAMING → SUSPENDED。 */
    public RealNameStatus suspend(RealNameStatus current) {
        if (current != RealNameStatus.REALNAMING) {
            throw new AccBusinessException(3007, "当前实名状态不允许暂停");
        }
        return RealNameStatus.SUSPENDED;
    }

    /** UT-A02：暂停后重试，SUSPENDED → REALNAMING。 */
    public RealNameStatus retry(RealNameStatus current) {
        if (current != RealNameStatus.SUSPENDED) {
            throw new AccBusinessException(3007, "当前实名状态不允许重试");
        }
        return RealNameStatus.REALNAMING;
    }

    /** UT-A09：NFC 强实名增强（I-06），BASE → ENHANCED；重复增强幂等。 */
    public RealNameLevel enhance(RealNameLevel level) {
        return RealNameLevel.ENHANCED;
    }
}
