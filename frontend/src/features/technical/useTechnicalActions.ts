import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { startTechnicalBackfill, startTechnicalUpdate } from "../../api/technical";
import { errorMessage } from "../../api/client";
import { useToast } from "../../components/Toast";

export function useTechnicalActions() {
  const navigate = useNavigate();
  const toast = useToast();

  const runUpdate = useCallback(async () => {
    try {
      const result = await startTechnicalUpdate();
      toast.push("Обновление технического анализа запущено", "success");
      navigate(`/workflows?focus=${result.workflow_id}`);
    } catch (reason) {
      toast.push(errorMessage(reason), "error");
    }
  }, [navigate, toast]);

  const runBackfill = useCallback(
    async (dateFrom: string, dateTo?: string) => {
      try {
        const result = await startTechnicalBackfill({
          date_from: dateFrom,
          date_to: dateTo,
        });
        toast.push("Backfill технического анализа запущен", "success");
        navigate(`/workflows?focus=${result.workflow_id}`);
      } catch (reason) {
        toast.push(errorMessage(reason), "error");
      }
    },
    [navigate, toast],
  );

  return { runUpdate, runBackfill };
}
