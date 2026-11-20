import { useEffect, useId, useRef, useSyncExternalStore, type InputHTMLAttributes } from "react";

/**
 * 담당자 이름을 이 브라우저에 기억해 두는 자리.
 *
 * 담당자 이름은 화면마다, 한 화면 안에서도 여러 번 요구됐다. 서버에는 감사
 * 표식으로만 쓰이고 인증이 아니므로(`docs/security.md`, AGENTS.md) 값 자체를
 * 브라우저에 남겨도 권한이 생기지 않는다. 저장 위치는 이 브라우저의
 * localStorage 하나이며 서버로 따로 보내지 않는다.
 */
const ACTOR_STORAGE_KEY = "bidops.actorName";
const REMEMBER_NOTE = "이 브라우저에 기억됩니다 · 로그인이나 신원 인증이 아닙니다.";

/** private mode나 storage 차단에서 접근 자체가 throw한다. 실패는 조용히 무시한다. */
export function readRememberedActorName(): string {
  return readRememberedActor();
}

function readRememberedActor(): string {
  try {
    return window.localStorage.getItem(ACTOR_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

/** 같은 탭의 다른 자리(사이드바 담당자 표시)에 기억된 이름이 바뀌었음을 알리는 이벤트. */
const ACTOR_CHANGE_EVENT = "bidops:actor-name";

function rememberActor(value: string): void {
  try {
    if (value.trim()) window.localStorage.setItem(ACTOR_STORAGE_KEY, value);
    else window.localStorage.removeItem(ACTOR_STORAGE_KEY);
  } catch {
    // 기억하지 못해도 입력 자체는 계속 동작해야 한다.
  }
  window.dispatchEvent(new Event(ACTOR_CHANGE_EVENT));
}

/** 이 브라우저에 기억된 담당자 이름을 바꾼다(사이드바 담당자 칸). 빈 값이면 지운다. */
export function setRememberedActorName(value: string): void {
  rememberActor(value);
}

function subscribeRememberedActor(onChange: () => void): () => void {
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key === ACTOR_STORAGE_KEY) onChange();
  };
  window.addEventListener(ACTOR_CHANGE_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(ACTOR_CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

/**
 * 이 브라우저에 기억된 담당자 이름(`bidops.actorName`). 셸 사이드바가 읽는다.
 * 저장소에 닿을 수 없으면 빈 문자열이다 — 이름을 지어내지 않는다. 감사 표식이며 인증이 아니다.
 */
export function useRememberedActorName(): string {
  return useSyncExternalStore(subscribeRememberedActor, readRememberedActor, () => "");
}

interface ActorFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "type" | "value"> {
  description?: string;
  label?: string;
  onChange: (value: string) => void;
  value: string;
  /** 기억 동작을 끄고 그 화면에서만 쓰는 이름으로 둘 때 false. */
  remember?: boolean;
  /** A compact decision panel can supply a complete description of remembering. */
  showRememberNote?: boolean;
}

/** 담당자가 스스로 적는 이름이며 감사 표식일 뿐 로그인·신원 인증·권한이 아니다. */
export function ActorField({
  description = "감사 귀속용 이름이며 로그인·신원 인증·권한 부여가 아닙니다.",
  id,
  label = "담당자 이름",
  maxLength = 128,
  onChange,
  value,
  remember = true,
  showRememberNote = true,
  ...inputProps
}: ActorFieldProps) {
  const generatedId = useId();
  const inputId = id ?? `actor-${generatedId}`;
  const descriptionId = `${inputId}-description`;
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const restored = useRef(false);

  // 비어 있을 때만 채운다. 사람이 이미 손댄 값을 기억된 값으로 덮지 않는다.
  useEffect(() => {
    if (!remember || restored.current || value !== "") return;
    restored.current = true;
    const remembered = readRememberedActor();
    if (remembered) onChangeRef.current(remembered);
  }, [remember, value]);

  return (
    <div className="actor-field">
      <label htmlFor={inputId}>{label}</label>
      <input
        {...inputProps}
        id={inputId}
        type="text"
        value={value}
        maxLength={maxLength}
        aria-describedby={descriptionId}
        onChange={(event) => {
          const next = event.target.value;
          if (remember) rememberActor(next);
          onChange(next);
        }}
      />
      <p id={descriptionId}>{remember && showRememberNote ? `${description} ${REMEMBER_NOTE}` : description}</p>
    </div>
  );
}
