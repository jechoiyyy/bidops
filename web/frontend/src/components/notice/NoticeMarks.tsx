import { StatusMark } from "../common/Marks";
import { GRADE_ORDER, gradeLabel } from "../../lib/grade";

export function NoticeGradeMark({ grade, label = gradeLabel(grade) }: { grade: string | null; label?: string }) {
  const level = GRADE_ORDER.findIndex((value) => value === grade) + 1;
  return <StatusMark gradeLevel={level || undefined} mark={{ label, tone: "neutral" }} />;
}
