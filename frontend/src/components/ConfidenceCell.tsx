import type { CandidateExplanation } from "../types/api";
import { confidenceTone, formatConfidence } from "../lib/format";
import { Badge } from "./ui/Badge";

interface Props {
  confidence: number;
  explanation: CandidateExplanation;
}

export function ConfidenceCell({ confidence, explanation }: Props) {
  return (
    <span
      className="inline-block cursor-help"
      title={explanation.human_readable}
    >
      <Badge tone={confidenceTone(confidence)}>
        {formatConfidence(confidence)}
      </Badge>
    </span>
  );
}
