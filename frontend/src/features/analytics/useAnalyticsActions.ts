import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { startFeatureBackfill, startFeatureUpdate } from "../../api/analytics";
import { errorMessage } from "../../api/client";
import { useToast } from "../../components/Toast";

export function useAnalyticsActions() {
  const navigate = useNavigate();
  const toast = useToast();

  const runUpdate = useCallback(async () => {
    try {
      const result = await startFeatureUpdate();
      toast.push("Обновление признаков запущено", "success");
      navigate(`/workflows?focus=${result.workflow_id}`);
    } catch (reason) {
      toast.push(errorMessage(reason), "error");
    }
  }, [navigate, toast]);

  const runBackfill = useCallback(
    async (dateFrom: string, dateTo?: string) => {
      try {
        const result = await startFeatureBackfill({ date_from: dateFrom, date_to: dateTo });
        toast.push("Пересчёт истории признаков запущен", "success");
        navigate(`/workflows?focus=${result.workflow_id}`);
      } catch (reason) {
        toast.push(errorMessage(reason), "error");
      }
    },
    [navigate, toast],
  );

  return { runUpdate, runBackfill };
}
