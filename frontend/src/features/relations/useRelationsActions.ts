import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { startRelationsBackfill, startRelationsComputeLatest } from "../../api/relations";
import { errorMessage } from "../../api/client";
import { useToast } from "../../components/Toast";

export function useRelationsActions() {
  const navigate = useNavigate();
  const toast = useToast();

  const runLatest = useCallback(async () => {
    try {
      const result = await startRelationsComputeLatest();
      toast.push("Расчёт связей запущен", "success");
      navigate(`/workflows?focus=${result.workflow_id}`);
    } catch (reason) {
      toast.push(errorMessage(reason), "error");
    }
  }, [navigate, toast]);

  const runBackfill = useCallback(
    async (asOfFrom: string, asOfTo?: string, cadence = "WEEKLY") => {
      try {
        const result = await startRelationsBackfill({
          as_of_from: asOfFrom,
          as_of_to: asOfTo,
          cadence,
        });
        toast.push("Backfill связей запущен", "success");
        navigate(`/workflows?focus=${result.workflow_id}`);
      } catch (reason) {
        toast.push(errorMessage(reason), "error");
      }
    },
    [navigate, toast],
  );

  return { runLatest, runBackfill };
}
