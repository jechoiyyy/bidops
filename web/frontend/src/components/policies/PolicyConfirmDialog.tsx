import { useEffect, useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import {
  CancelButton,
  CriteriaDialog,
  DialogActions,
  Facts,
  Note,
} from "../criteria/CriteriaPrimitives";

/**
 * 후보 지정과 운영 활성화의 확인 단계.
 *
 * 두 조작 모두 불변 정책의 상태를 바꾸고 되돌리려면 새 버전이 필요하므로, 무엇을
 * 어떤 근거로 바꾸는지 화면이 다시 보여 준 뒤에만 요청이 나간다. 브라우저 confirm은
 * 결합 입력(정책·게이트·모델·프로필·담당자)을 되풀이해 보여 줄 자리가 없어 쓰지 않는다.
 *
 * 세 가지를 고정한다.
 *
 *  1. **대상과 근거.** 창이 열린 순간의 정책·evaluation·결합 입력을 그대로 들고
 *     있으며, 뒤에서 목록이 새로 고쳐지거나 담당자가 다른 정책을 골라도 바뀌지
 *     않는다. 요청도 고정된 값으로 나간다.
 *  2. **담당자.** 확인 대상이 바뀌면(`snapshotKey`) 이름을 비운다. 앞 대상에 적은
 *     이름이 다음 대상의 확인에 그대로 쓰이면 감사 기록이 틀린다.
 *  3. **진행 중 닫기 금지.** 요청이 나간 뒤에는 취소·X·Esc로 닫히지 않는다. 응답을
 *     보기 전에 창이 닫히면 담당자는 상태가 바뀌었는지 모른 채 다시 누른다.
 */

export interface PolicyConfirmSnapshot {
  kind: "candidate" | "activate";
  policyVersion: string;
  /** 활성화에만 있다. 후보 지정에는 근거 evaluation이 필요 없다. */
  evaluationId: string | null;
  facts: [string, string][];
}

function snapshotKey(snapshot: PolicyConfirmSnapshot | null): string {
  return snapshot ? `${snapshot.kind}:${snapshot.policyVersion}:${snapshot.evaluationId ?? ""}` : "";
}

export function PolicyConfirmDialog({ snapshot, busy, error, onClose, onConfirm }: {
  snapshot: PolicyConfirmSnapshot | null;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onConfirm: (snapshot: PolicyConfirmSnapshot, actor: string) => void;
}) {
  const [actor, setActor] = useState("");
  const key = snapshotKey(snapshot);
  // 대상이 바뀌면 이름을 비운다. 같은 대상에서 409가 났을 때는 그대로 남는다.
  useEffect(() => { setActor(""); }, [key]);

  const activating = snapshot?.kind === "activate";
  const ready = actor.trim().length > 0 && !busy;

  function close() {
    // 요청이 나간 뒤에는 닫지 않는다. 응답이 창을 닫거나 오류를 남긴다.
    if (busy) return;
    onClose();
  }

  return (
    <CriteriaDialog
      onClose={close}
      open={snapshot !== null}
      title={activating ? "판정 정책을 운영에 활성화합니다" : "운영 활성화 후보로 지정합니다"}
    >
      {snapshot ? (
        <>
          <Facts items={snapshot.facts.map(([term, value]) => [term, <span className="crit-mono" key={term}>{value}</span>])} />
          <Note
            title={activating
              ? "이후 시작하는 실행의 정책을 바꿉니다"
              : "후보 지정은 운영 활성화가 아닙니다"}
            tone="warning"
          >
            정책 본문은 불변입니다. 이 상태 변경을 되돌리려면 새 버전을 만들어야 하며, 이미 기록된 판정과 사람의 결정은 바뀌지 않습니다.
          </Note>
          <TextInput
            isDisabled={busy}
            label={activating ? "활성화 담당자 · 필수" : "확인 담당자 · 필수"}
            onChange={setActor}
            placeholder="담당자 이름"
            value={actor}
          />
          <Text as="span" className="crit-small" color="secondary">
            담당자 이름은 감사 표식이며 로그인이나 신원 인증이 아닙니다.
          </Text>
          {error ? <Text as="p" className="crit-error" role="alert">{error}</Text> : null}
          <DialogActions>
            <CancelButton isDisabled={busy} onClick={close} />
            <Button
              isDisabled={!ready}
              label={busy ? "요청 중…" : activating ? "정책 활성화" : "후보로 지정"}
              onClick={() => onConfirm(snapshot, actor.trim())}
              size="sm"
              variant="primary"
            />
          </DialogActions>
        </>
      ) : null}
    </CriteriaDialog>
  );
}
