import type { CandidateExplanation } from "../types/api";
import { confidenceTone, formatConfidence } from "../lib/format";
import { Badge } from "./ui/Badge";

interface Props {
  confidence: number;
  explanation: CandidateExplanation;
  /**
   * Приглушить бейдж до нейтрального тона — для строк с принятым решением,
   * чтобы красный/жёлтый score не спорил с цветом статуса «Подтверждено».
   */
  muted?: boolean;
}

export function ConfidenceCell({ confidence, explanation, muted }: Props) {
  return (
    <span
      className="inline-block cursor-help"
      title={explanation.human_readable}
    >
      <Badge tone={muted ? "neutral" : confidenceTone(confidence)}>
        {formatConfidence(confidence)}
      </Badge>
    </span>
  );
}
