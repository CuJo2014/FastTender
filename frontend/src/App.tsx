import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./components/AppLayout";
import { SpecificationsListPage } from "./pages/SpecificationsListPage";
import { SpecificationUploadPage } from "./pages/SpecificationUploadPage";
import { SpecificationDetailPage } from "./pages/SpecificationDetailPage";
import { CatalogPage } from "./pages/CatalogPage";
import { SuppliersPage } from "./pages/SuppliersPage";
import { ClientsPage } from "./pages/ClientsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/specifications" replace />} />
        <Route path="/specifications" element={<SpecificationsListPage />} />
        <Route path="/specifications/upload" element={<SpecificationUploadPage />} />
        <Route path="/specifications/:specId" element={<SpecificationDetailPage />} />
        <Route path="/catalog" element={<CatalogPage />} />
        <Route path="/suppliers" element={<SuppliersPage />} />
        <Route path="/clients" element={<ClientsPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

function NotFound() {
  return (
    <div className="p-8 text-center text-slate-500">
      Страница не найдена.
    </div>
  );
}
