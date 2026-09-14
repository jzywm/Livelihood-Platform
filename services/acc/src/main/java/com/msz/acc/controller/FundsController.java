package com.msz.acc.controller;

import com.msz.acc.application.FundsAuditService;
import com.msz.acc.application.ReconcileFlow;
import com.msz.acc.application.ReconcileResult;
import com.msz.acc.controller.dto.FundsAuditFlowView;
import com.msz.acc.controller.support.ControllerSupport;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.infrastructure.auth.AuthContext;
import com.msz.acc.infrastructure.web.TraceIds;
import com.msz.common.api.ApiConventions;
import com.msz.common.api.Envelope;
import com.msz.common.api.PageResult;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;
import java.util.List;
import java.util.Set;

/**
 * 监管端资金审计/对账接口（openapi /acc/funds/audit、/acc/funds/reconcile）：
 * 仅 REGULATOR（403 否则）；reconcileStatus 筛选枚举校验；diff&gt;0 时 Envelope code 仍 0、
 * data.status=DIFF（alertCode 3009 由内部告警钩子触发，本版本记日志）。
 */
@RestController
public class FundsController {

    private static final Logger log = LoggerFactory.getLogger(FundsController.class);
    private static final Set<String> RECONCILE_STATUSES = Set.of("PENDING", "RECONCILED", "DIFF");

    private final FundsAuditService fundsAuditService;
    private final ReconcileFlow reconcileFlow;

    public FundsController(FundsAuditService fundsAuditService, ReconcileFlow reconcileFlow) {
        this.fundsAuditService = fundsAuditService;
        this.reconcileFlow = reconcileFlow;
    }

    @GetMapping("/acc/funds/audit")
    public Envelope<PageResult<FundsAuditFlowView>> audit(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int pageSize,
            @RequestParam(required = false) String from,
            @RequestParam(required = false) String to,
            @RequestParam(required = false) String reconcileStatus,
            HttpServletRequest request) {
        AuthContext ctx = ControllerSupport.requireAuth(request);
        ControllerSupport.requireRegulator(ctx);
        if (reconcileStatus != null && !RECONCILE_STATUSES.contains(reconcileStatus)) {
            throw new AccBusinessException(1003, "reconcileStatus 枚举非法（PENDING/RECONCILED/DIFF）");
        }
        LocalDate fromDate = ControllerSupport.parseDate(from);
        LocalDate toDate = ControllerSupport.parseDate(to);

        PageResult<FundsAuditService.AuditItem> result =
                fundsAuditService.audit(page, pageSize, fromDate, toDate, reconcileStatus);
        List<FundsAuditFlowView> views = result.list().stream()
                .map(item -> new FundsAuditFlowView(
                        "flw_" + item.flow().getFlowId(), item.flow().getType(), item.flow().getDirection(),
                        item.flow().getAmount(), item.flow().getStatus(), item.flow().getChannelOrderNo(),
                        item.flow().getBizType(), item.flow().getHash(), item.flow().getOccurredAt(),
                        null, "acc_" + item.flow().getAccountId(), null, item.reconcileStatus()))
                .toList();
        return Envelope.ok(new PageResult<>(views, result.total(), result.page(), result.pageSize()),
                TraceIds.of(request));
    }

    @PostMapping("/acc/funds/reconcile")
    public Envelope<ReconcileView> reconcile(
            @RequestBody ReconcileBody body,
            @RequestHeader(value = ApiConventions.IDEMPOTENCY_KEY_HEADER, required = false) String idempotencyKey,
            HttpServletRequest request) {
        AuthContext ctx = ControllerSupport.requireAuth(request);
        ControllerSupport.requireRegulator(ctx);
        if (idempotencyKey == null || idempotencyKey.isBlank()) {
            throw new AccBusinessException(1001, "Idempotency-Key 缺失（资金类写操作强制）");
        }
        if (body.from() == null || body.from().isBlank()) {
            throw new AccBusinessException(1001, "from 缺失");
        }
        if (body.to() == null || body.to().isBlank()) {
            throw new AccBusinessException(1001, "to 缺失");
        }
        ReconcileResult result = reconcileFlow.trigger(body.from(), body.to(), idempotencyKey);
        if (result.alertCode() == 3009) {
            log.warn("资金对账不一致告警钩子 [reconcileId={}] diffCount={}",
                    result.reconcileId(), result.diffCount());
        }
        return Envelope.ok(new ReconcileView(result.reconcileId(), result.status(), result.diffCount()),
                TraceIds.of(request));
    }

    /** openapi ReconcileRequest。 */
    public record ReconcileBody(String from, String to) {
    }

    /** openapi ReconcileResult（不含内部 alertCode）。 */
    public record ReconcileView(String reconcileId, String status, long diffCount) {
    }
}
