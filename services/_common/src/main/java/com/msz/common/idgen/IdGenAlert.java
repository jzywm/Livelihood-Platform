package com.msz.common.idgen;

/**
 * 发号告警钩子：level 取值 0=P0（拒绝发号） / 1=P1 / 2=P2。
 */
public interface IdGenAlert {

    void alert(int level, String message);
}
