package com.msz.acc.controller;

import com.msz.acc.application.WalletFlowQueryService;
import com.msz.acc.application.WalletSummary;
import com.msz.acc.controller.dto.WalletFlowView;
import com.msz.acc.controller.support.ControllerSupport;
import com.msz.acc.domain.model.WalletFlow;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.infrastructure.auth.AuthContext;
import com.msz.acc.infrastructure.web.TraceIds;
import com.msz.common.api.Envelope;
import com.msz.common.api.PageResult;
import jakarta.servlet.http.HttpServletRequest;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

/**
 * 钱包记账接口（openapi /acc/wallet/flows、/summary、/flows/export）：
 * 流水无 PII 直接返回；导出为 MFA 敏感操作（2003）+ POI xlsx（表头+行，上限 10000 行）。
 */
@RestController
public class WalletController {

    private static final String XLSX_CONTENT_TYPE =
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
    private static final String[] HEADERS = {"flowId", "type", "direction", "amount", "status",
            "channelOrderNo", "bizType", "hash", "occurredAt"};
    private static final int EXPORT_PAGE_SIZE = 100;
    private static final int EXPORT_MAX_ROWS = 10000;

    private final WalletFlowQueryService queryService;

    public WalletController(WalletFlowQueryService queryService) {
        this.queryService = queryService;
    }

    @GetMapping("/acc/wallet/flows")
    public Envelope<PageResult<WalletFlowView>> flows(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int pageSize,
            @RequestParam(required = false) String type,
            @RequestParam(required = false) String from,
            @RequestParam(required = false) String to,
            HttpServletRequest request) {
        AuthContext ctx = ControllerSupport.requireAuth(request);
        long accountId = ControllerSupport.accountIdOf(ctx);
        LocalDate fromDate = ControllerSupport.parseDate(from);
        LocalDate toDate = ControllerSupport.parseDate(to);
        PageResult<WalletFlow> result = queryService.query(accountId, type, fromDate, toDate, page, pageSize);
        List<WalletFlowView> views = result.list().stream().map(WalletFlowView::of).toList();
        return Envelope.ok(new PageResult<>(views, result.total(), result.page(), result.pageSize()),
                TraceIds.of(request));
    }

    @GetMapping("/acc/wallet/summary")
    public Envelope<WalletSummary> summary(HttpServletRequest request) {
        AuthContext ctx = ControllerSupport.requireAuth(request);
        WalletSummary summary = queryService.summary(ControllerSupport.accountIdOf(ctx));
        return Envelope.ok(summary, TraceIds.of(request));
    }

    @GetMapping("/acc/wallet/flows/export")
    public ResponseEntity<byte[]> export(@RequestParam(required = false) String type,
                                         @RequestParam(required = false) String from,
                                         @RequestParam(required = false) String to,
                                         HttpServletRequest request) {
        AuthContext ctx = ControllerSupport.requireAuth(request);
        if (!ctx.mfa()) {
            throw new AccBusinessException(2003, "MFA 未通过");
        }
        long accountId = ControllerSupport.accountIdOf(ctx);
        LocalDate fromDate = ControllerSupport.parseDate(from);
        LocalDate toDate = ControllerSupport.parseDate(to);

        List<WalletFlow> all = new ArrayList<>();
        for (int page = 1; page <= EXPORT_MAX_ROWS / EXPORT_PAGE_SIZE; page++) {
            PageResult<WalletFlow> pageResult =
                    queryService.query(accountId, type, fromDate, toDate, page, EXPORT_PAGE_SIZE);
            all.addAll(pageResult.list());
            if (pageResult.list().size() < EXPORT_PAGE_SIZE) {
                break;
            }
        }
        byte[] xlsx = buildXlsx(all);
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_TYPE, XLSX_CONTENT_TYPE)
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"flows.xlsx\"")
                .body(xlsx);
    }

    private byte[] buildXlsx(List<WalletFlow> flows) {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            Sheet sheet = workbook.createSheet("flows");
            Row header = sheet.createRow(0);
            for (int i = 0; i < HEADERS.length; i++) {
                header.createCell(i).setCellValue(HEADERS[i]);
            }
            int rowIndex = 1;
            for (WalletFlow flow : flows) {
                Row row = sheet.createRow(rowIndex++);
                row.createCell(0).setCellValue("flw_" + flow.getFlowId());
                row.createCell(1).setCellValue(flow.getType());
                row.createCell(2).setCellValue(flow.getDirection());
                row.createCell(3).setCellValue(flow.getAmount());
                row.createCell(4).setCellValue(flow.getStatus());
                row.createCell(5).setCellValue(flow.getChannelOrderNo());
                row.createCell(6).setCellValue(flow.getBizType());
                row.createCell(7).setCellValue(flow.getHash());
                row.createCell(8).setCellValue(String.valueOf(flow.getOccurredAt()));
            }
            workbook.write(out);
            return out.toByteArray();
        } catch (IOException e) {
            throw new IllegalStateException("xlsx 生成失败", e);
        }
    }
}
