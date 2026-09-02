import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import ApplicantList from "./screens/ApplicantList";
import ApplicantDetail from "./screens/ApplicantDetail";
import ApplicantIntake from "./screens/ApplicantIntake";
import ScoreSimulator from "./screens/ScoreSimulator";
import SummaryView from "./screens/SummaryView";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<ApplicantList />} />
        <Route path="/applicant/:id" element={<ApplicantDetail />} />
        <Route path="/apply" element={<ApplicantIntake />} />
        <Route path="/simulator" element={<ScoreSimulator />} />
        <Route path="/summary" element={<SummaryView />} />
      </Route>
    </Routes>
  );
}
