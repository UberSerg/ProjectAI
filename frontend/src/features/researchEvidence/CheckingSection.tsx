import type { EvidenceExperiment } from "../../api/researchEvidence";
import { DEFAULT_CHECKING } from "./constants";

export function CheckingSection({ experiment }: { experiment?: EvidenceExperiment | null }) {
  const items = experiment?.checking?.length ? experiment.checking : DEFAULT_CHECKING;
  return (
    <div className="card" data-testid="evidence-checking">
      <h3>Что проверяем</h3>
      {experiment?.purpose ? <p>{experiment.purpose}</p> : null}
      <ul className="plain-list">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
