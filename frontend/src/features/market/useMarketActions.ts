import { useNavigate } from "react-router-dom";
import { errorMessage } from "../../api/client";
import {
  runBackfill,
  runDataQuality,
  runMarketUpdate,
  type BackfillRequest,
} from "../../api/market";
import { useToast } from "../../components/Toast";
import { labels } from "../../utils/labels";

export function useMarketActions() {
  const toast = useToast();
  const navigate = useNavigate();

  async function withBusy<T>(action: () => Promise<T>, busy: (v: boolean) => void): Promise<T | null> {
    busy(true);
    try {
      return await action();
    } catch (reason) {
      toast.push(errorMessage(reason), "error");
      return null;
    } finally {
      busy(false);
    }
  }

  async function startUpdate(busy: (v: boolean) => void) {
    const result = await withBusy(runMarketUpdate, busy);
    if (!result) return;
    toast.push(`Обновление запущено · процесс ${result.workflow_id}`, "success");
    navigate(`/workflows?focus=${result.workflow_id}`);
  }

  async function startBackfill(request: BackfillRequest, busy: (v: boolean) => void) {
    const result = await withBusy(() => runBackfill(request), busy);
    if (!result) return;
    toast.push(`Загрузка истории запущена · процесс ${result.workflow_id}`, "success");
    navigate(`/workflows?focus=${result.workflow_id}`);
  }

  async function startDq(busy: (v: boolean) => void) {
    const result = await withBusy(runDataQuality, busy);
    if (!result) return;
    toast.push(`Проверка качества запущена · процесс ${result.workflow_id}`, "success");
    navigate(`/workflows?focus=${result.workflow_id}`);
  }

  return { startUpdate, startBackfill, startDq, labels };
}
