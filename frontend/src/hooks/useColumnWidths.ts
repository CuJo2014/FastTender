import { useCallback, useState } from "react";

/**
 * Глобальные ширины колонок таблицы строк спеки.
 *
 * Хранятся в localStorage как `{columnId: px}` — одна раскладка на все спеки.
 * Ключуем по СТАБИЛЬНОМУ columnId (не по индексу): это закладка под будущие
 * кастомные колонки на покупателя — мапа устойчива к разным наборам колонок.
 * Это преференс пользователя (localStorage), не покупателя.
 */
const STORAGE_KEY = "spec.columnWidths";
const MIN_WIDTH = 60;

type Widths = Record<string, number>;

function load(): Widths {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Widths) : {};
  } catch {
    return {};
  }
}

function save(w: Widths): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(w));
  } catch {
    // приватный режим / переполнение — молча игнорируем
  }
}

export function useColumnWidths() {
  const [widths, setWidths] = useState<Widths>(load);

  const setWidth = useCallback((id: string, px: number) => {
    setWidths((prev) => {
      const next = { ...prev, [id]: Math.max(MIN_WIDTH, Math.round(px)) };
      save(next);
      return next;
    });
  }, []);

  const resetWidth = useCallback((id: string) => {
    setWidths((prev) => {
      const next = { ...prev };
      delete next[id];
      save(next);
      return next;
    });
  }, []);

  const resetAll = useCallback(() => {
    setWidths({});
    save({});
  }, []);

  return { widths, setWidth, resetWidth, resetAll };
}
