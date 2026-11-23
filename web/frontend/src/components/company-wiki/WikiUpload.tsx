import { Button } from "@astryxdesign/core/Button";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../../lib/api";
import { ingestDetail, ingestListKey, uploadIngest } from "../../lib/companyWikiIngestApi";
import type { WikiProject } from "../../lib/companyWikiApi";
import { generateRequestId } from "../../lib/requestId";
import { requestActorInput, useRememberedActorName } from "../common/ActorField";
import { CancelButton, CriteriaDialog, DialogActions } from "../criteria/CriteriaPrimitives";
import { wikiUrl } from "./WikiBody";
import { IngestProblem } from "./IngestProblem";
import { wikiValue } from "./WikiState";

export function WikiUpload({ project }: { project: WikiProject }) {
  const actor = useRememberedActorName().trim();
  const [open, setOpen] = useState(false);
  const [needsName, setNeedsName] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const receipt = useRef<{ actor: string; file: File; key: string } | null>(null);
  const client = useQueryClient();
  const navigate = useNavigate();
  const upload = useMutation({
    mutationFn: (input: File) => {
      if (receipt.current?.file !== input || receipt.current.actor !== actor) {
        receipt.current = { key: generateRequestId(), file: input, actor };
      }
      return uploadIngest(project.id, input, actor, receipt.current.key);
    },
    onSuccess: run => {
      client.setQueryData(ingestDetail(run.id).queryKey, run);
      void client.invalidateQueries({ queryKey: ingestListKey });
      navigate(wikiUrl("ingests", { run: run.id }));
    },
    onError: error => {
      if (error instanceof ApiError && error.status >= 400 && error.status < 500) receipt.current = null;
    },
  });
  function checkName() {
    if (actor) return true;
    setNeedsName(true);
    setOpen(false);
    requestActorInput();
    return false;
  }
  return <>
    <Button label="실적 넣기" variant="primary" onClick={() => {
      if (checkName()) { setFile(null); upload.reset(); setOpen(true); }
    }}/>
    {needsName && !actor && <p role="status">사이드바에 담당자 이름을 입력해 주세요.</p>}
    {open && <CriteriaDialog open title="실적 넣기" onClose={() => { if (!upload.isPending) setOpen(false); }}>
      <p>대상 실적 · {project.id} {wikiValue(project.title)}</p>
      <p>담당자 · {actor}</p>
      <label className="wiki-dialog-field">제안요청서 파일 (HWP·HWPX·PDF, 최대 50 MiB)
        <input type="file" accept=".hwp,.hwpx,.pdf" disabled={upload.isPending}
          onChange={event => { setFile(event.target.files?.[0] ?? null); upload.reset(); }}/>
      </label>
      {upload.error && <IngestProblem error={upload.error}/>}
      <DialogActions><CancelButton isDisabled={upload.isPending} onClick={() => setOpen(false)}/>
        <Button label="파일 제출" isDisabled={!file || upload.isPending}
          onClick={() => { if (file && checkName()) upload.mutate(file); }}/>
      </DialogActions>
    </CriteriaDialog>}
  </>;
}
