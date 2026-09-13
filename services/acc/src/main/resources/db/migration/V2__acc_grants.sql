-- V2：最小权限应用账号 acc_app（裁决：SEC-09 / UT-B03）
-- 主数据表：SELECT/INSERT/UPDATE；wallet_flow_*：仅 SELECT/INSERT（库层只增不改，无 UPDATE/DELETE）。

CREATE USER IF NOT EXISTS 'acc_app'@'%' IDENTIFIED BY 'acc_app_pwd';

GRANT SELECT, INSERT, UPDATE ON acc.account TO 'acc_app'@'%';
GRANT SELECT, INSERT, UPDATE ON acc.realname_record TO 'acc_app'@'%';
GRANT SELECT, INSERT, UPDATE ON acc.wallet_binding TO 'acc_app'@'%';
GRANT SELECT, INSERT, UPDATE ON acc.reconcile_task TO 'acc_app'@'%';
GRANT SELECT, INSERT, UPDATE ON acc.acc_idempotency_record TO 'acc_app'@'%';

GRANT SELECT, INSERT ON acc.wallet_flow_202507 TO 'acc_app'@'%';
GRANT SELECT, INSERT ON acc.wallet_flow_202508 TO 'acc_app'@'%';
GRANT SELECT, INSERT ON acc.wallet_flow_202509 TO 'acc_app'@'%';
GRANT SELECT, INSERT ON acc.wallet_flow_202510 TO 'acc_app'@'%';
GRANT SELECT, INSERT ON acc.wallet_flow_202511 TO 'acc_app'@'%';
GRANT SELECT, INSERT ON acc.wallet_flow_202512 TO 'acc_app'@'%';
GRANT SELECT, INSERT ON acc.wallet_flow_202601 TO 'acc_app'@'%';
GRANT SELECT, INSERT ON acc.wallet_flow_202602 TO 'acc_app'@'%';
GRANT SELECT, INSERT ON acc.wallet_flow_202603 TO 'acc_app'@'%';
GRANT SELECT, INSERT ON acc.wallet_flow_202604 TO 'acc_app'@'%';
GRANT SELECT, INSERT ON acc.wallet_flow_202605 TO 'acc_app'@'%';
GRANT SELECT, INSERT ON acc.wallet_flow_202606 TO 'acc_app'@'%';
GRANT SELECT, INSERT ON acc.wallet_flow_202607 TO 'acc_app'@'%';
GRANT SELECT, INSERT ON acc.wallet_flow_202608 TO 'acc_app'@'%';

FLUSH PRIVILEGES;
