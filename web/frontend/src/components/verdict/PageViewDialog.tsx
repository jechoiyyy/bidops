import { useQuery } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { getDocumentStructurePage } from "../deep-review/api";
import { MutationFeedback } from "../common/MutationFeedback";
import { describeApiError } from "../../lib/apiErrors";

/*
 * "쪽 전체 보기": 기존 `GET /api/document-structures/{id}/pages/{page}`가 주는 그 쪽의 블록 원문을
 * 그대로 읽어 보여 준다. 근거 인용이 가리키는 블록(`block_key`)은 `<mark>`로 표시한다. 화면은 글자를
 * 고치거나 쪽 번호를 짐작해 바꾸지 않고, 파일·객체 경로는 응답에도 없다. 열려 있을 때만 읽는다.
 */

interface PageViewDialogProps {
  open: boolean;
  onClose: () => void;
  structureId: string | null;
  page: number | null;
  /** 근거 인용이 가리키는 블록. 없으면 표시하지 않는다. */
  highlightBlockKeys: readonly string[];
}

export function PageViewDialog({ open, onClose, structureId, page, highlightBlockKeys }: PageViewDialogProps) {
  const enabled = open && structureId !== null && page !== null;
  const query = useQuery({
    queryKey: ["verdict-source-page", structureId, page],
    queryFn: () => getDocumentStructurePage(structureId as string, page as number),
    enabled,
    retry: false,
    staleTime: 30_000,
  });
  return (
    <Dialog
      isOpen={open}
      maxHeight="90dvh"
      onOpenChange={(next) => { if (!next) onClose(); }}
      padding={6}
      purpose="info"
      width="calc(var(--spacing-12) * 16)"
    >
      <div className="opportunity-dialog-body">
        <DialogHeader onOpenChange={(next) => { if (!next) onClose(); }} title={page === null ? "원문 쪽 전체" : `원문 ${page}쪽 전체`} />
        {query.isPending && enabled ? <p role="status">쪽을 불러오는 중입니다.</p> : null}
        {query.isError ? (
          <MutationFeedback
            onRecover={() => { void query.refetch(); }}
            problem={describeApiError(query.error, "원문 쪽을 불러오지 못했습니다.")}
            tone="error"
          />
        ) : null}
        {query.data ? (
          query.data.blocks.length === 0 ? (
            <p>이 쪽에 저장된 블록이 없습니다.</p>
          ) : (
            <ol aria-label="쪽 블록" className="vd-page-blocks">
              {query.data.blocks.map((block, index) => (
                <li className="vd-page-block" key={index}>
                  {highlightBlockKeys.includes(block.block_key) ? <mark>{block.text}</mark> : block.text}
                </li>
              ))}
            </ol>
          )
        ) : null}
        <div className="opportunity-dialog-actions">
          <Button label="닫기" onClick={onClose} />
        </div>
      </div>
    </Dialog>
  );
}
