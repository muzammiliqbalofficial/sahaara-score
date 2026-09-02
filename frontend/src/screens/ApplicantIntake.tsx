import { useState, useCallback } from "react";
import {
  User, FileText, Upload, CheckCircle2, ArrowRight, ArrowLeft,
  MapPin, Users, Briefcase, Zap, GraduationCap, Banknote,
  Globe, Shield,
} from "lucide-react";
import { post } from "../api/client";

type Lang = "en" | "ur";

interface Translations {
  title: string;
  subtitle: string;
  step1Title: string;
  step2Title: string;
  step3Title: string;
  cnic: string;
  cnicPlaceholder: string;
  city: string;
  dependants: string;
  occupation: string;
  next: string;
  back: string;
  submit: string;
  uploadUtility: string;
  uploadMarksheet: string;
  uploadIncome: string;
  dropHint: string;
  submitting: string;
  submitted: string;
  scorePreview: string;
  guidance: string;
  langToggle: string;
}

const T: Record<Lang, Translations> = {
  en: {
    title: "Citizen Application Portal",
    subtitle: "Apply for financial support through the Sahaara Score system",
    step1Title: "Personal & Family Information",
    step2Title: "Document Upload",
    step3Title: "Review & Submit",
    cnic: "CNIC Number",
    cnicPlaceholder: "XXXXX-XXXXXXX-X",
    city: "City",
    dependants: "Family Dependents",
    occupation: "Occupation",
    next: "Continue",
    back: "Back",
    submit: "Submit Application",
    uploadUtility: "Utility Bill (K-Electric / LESCO / SNGPL)",
    uploadMarksheet: "Academic Marksheet",
    uploadIncome: "Income Slip / Affidavit",
    dropHint: "Drag & drop or click to upload (JPG, PNG, PDF)",
    submitting: "Processing your application...",
    submitted: "Application Submitted Successfully!",
    scorePreview: "Estimated Sahaara Score",
    guidance: "Your application will be reviewed within 5-7 business days.",
    langToggle: "اردو",
  },
  ur: {
    title: "شہری درخواست پورٹل",
    subtitle: "سہارا اسکور سسٹم کے ذریعے مالی معاونت کے لیے درخواست دیں",
    step1Title: "ذاتی اور خاندانی معلومات",
    step2Title: "دستاویزات اپ لوڈ",
    step3Title: "جائزہ اور جمع",
    cnic: "شناختی کارڈ نمبر",
    cnicPlaceholder: "XXXXX-XXXXXXX-X",
    city: "شہر",
    dependants: "خاندان کے افراد",
    occupation: "پیشہ",
    next: "آگے",
    back: "واپس",
    submit: "درخواست جمع کروائیں",
    uploadUtility: "یوٹیلٹی بل (کے الیکٹرک / لیسکو / ایس این جی پی ایل)",
    uploadMarksheet: "تعلیمی مارک شیٹ",
    uploadIncome: "آمدنی کا سلپ / حلف نامہ",
    dropHint: "ڈریگ اینڈ ڈراپ یا کلک کرکے اپ لوڈ کریں",
    submitting: "آپ کی درخواست پروسیس ہو رہی ہے...",
    submitted: "درخواست کامیابی سے جمع ہو گئی!",
    scorePreview: "متوقع سہارا اسکور",
    guidance: "آپ کی درخواست 5-7 کاروباری دنوں میں جائزہ لیا جائے گا۔",
    langToggle: "English",
  },
};

const CITIES = ["Karachi", "Lahore", "Islamabad", "Rawalpindi", "Faisalabad", "Multan", "Peshawar", "Quetta"];
const OCCUPATIONS = ["Freelancer", "Daily Wager", "Shopkeeper", "Farmer", "Student", "Homemaker", "Other"];

interface FormData {
  cnic: string;
  city: string;
  dependants: number;
  occupation: string;
  utilityFile: File | null;
  marksheetFile: File | null;
  incomeFile: File | null;
}

export default function ApplicantIntake() {
  const [lang, setLang] = useState<Lang>("en");
  const t = T[lang];
  const isUrdu = lang === "ur";

  const [step, setStep] = useState(1);
  const [form, setForm] = useState<FormData>({
    cnic: "",
    city: "Lahore",
    dependants: 2,
    occupation: "Freelancer",
    utilityFile: null,
    marksheetFile: null,
    incomeFile: null,
  });

  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [estimatedScore, setEstimatedScore] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const updateField = useCallback(<K extends keyof FormData>(key: K, value: FormData[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
  }, []);

  const formatCnic = (raw: string) => {
    const digits = raw.replace(/\D/g, "").slice(0, 15);
    if (digits.length <= 5) return digits;
    if (digits.length <= 12) return `${digits.slice(0, 5)}-${digits.slice(5)}`;
    return `${digits.slice(0, 5)}-${digits.slice(5, 12)}-${digits.slice(12)}`;
  };

  const handleFileSelect = useCallback(
    (field: "utilityFile" | "marksheetFile" | "incomeFile") => (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0] ?? null;
      updateField(field, file);
    },
    [updateField],
  );

  const estimateScore = () => {
    let score = 35;
    if (form.occupation === "Freelancer" || form.occupation === "Shopkeeper") score += 10;
    if (form.dependants <= 3) score += 8;
    else if (form.dependants <= 5) score += 4;
    if (form.utilityFile) score += 12;
    if (form.marksheetFile) score += 10;
    if (form.incomeFile) score += 8;
    return Math.min(score, 100);
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      // Create applicant.
      const applicant = await post<{ id: string }>("/applicants", {
        identity_reference: form.cnic,
        city: form.city,
        district: form.city,
        applicant_type: "student",
        dependants: form.dependants,
      });

      // Parse and attach documents.
      const docTypes = [
        { file: form.utilityFile, endpoint: "/documents/parse-utility-bill" },
        { file: form.marksheetFile, endpoint: "/documents/parse-academic-record" },
        { file: form.incomeFile, endpoint: "/documents/parse-income-slip" },
      ];

      for (const { file, endpoint } of docTypes) {
        if (!file) continue;
        const fd = new FormData();
        fd.append("file", file);
        await fetch(`/api/v1${endpoint}?applicant_id=${applicant.id}`, {
          method: "POST",
          body: fd,
        });
      }

      // Trigger scoring.
      const assessment = await post<{ score: number }>(
        `/assessments/${applicant.id}/score`,
        {},
      );

      setEstimatedScore(assessment.score);
      setSubmitted(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-[calc(100vh-8rem)] intake-gradient">
      <div className="mx-auto max-w-3xl px-4 py-8">
        {/* Header */}
        <div className="mb-8 text-center">
          <div className="flex items-center justify-center gap-2 mb-2">
            <Shield className="h-6 w-6 text-blue-600" />
            <h1 className={`text-2xl font-bold ${isUrdu ? "urdu-text" : ""}`}>
              {t.title}
            </h1>
          </div>
          <p className={`text-sm text-gray-500 ${isUrdu ? "urdu-text" : ""}`}>
            {t.subtitle}
          </p>
          <button
            onClick={() => setLang((l) => (l === "en" ? "ur" : "en"))}
            className="mt-2 inline-flex items-center gap-1 rounded-full bg-white/80 px-3 py-1 text-xs font-medium text-gray-600 ring-1 ring-gray-200 hover:bg-white transition"
          >
            <Globe className="h-3.5 w-3.5" />
            {t.langToggle}
          </button>
        </div>

        {/* Step indicator */}
        {!submitted && (
          <div className="mb-6 flex items-center justify-center gap-2">
            {[1, 2, 3].map((s) => (
              <div key={s} className="flex items-center gap-2">
                <div
                  className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-semibold transition-all ${
                    step >= s
                      ? "bg-blue-600 text-white shadow-md"
                      : "bg-gray-200 text-gray-500"
                  }`}
                >
                  {step > s ? <CheckCircle2 className="h-4 w-4" /> : s}
                </div>
                {s < 3 && (
                  <div
                    className={`h-0.5 w-12 rounded transition-colors ${
                      step > s ? "bg-blue-600" : "bg-gray-200"
                    }`}
                  />
                )}
              </div>
            ))}
          </div>
        )}

        {/* Step content */}
        <div className="card animate-fade-in">
          {submitted ? (
            <SuccessView t={t} score={estimatedScore} isUrdu={isUrdu} />
          ) : step === 1 ? (
            <Step1 form={form} t={t} updateField={updateField} formatCnic={formatCnic} isUrdu={isUrdu} />
          ) : step === 2 ? (
            <Step2 form={form} t={t} handleFileSelect={handleFileSelect} isUrdu={isUrdu} />
          ) : (
            <Step3 form={form} t={t} estimateScore={estimateScore} isUrdu={isUrdu} />
          )}

          {/* Navigation */}
          {!submitted && (
            <div className="mt-6 flex items-center justify-between border-t border-gray-100 pt-4">
              {step > 1 ? (
                <button
                  onClick={() => setStep((s) => s - 1)}
                  className="btn-secondary"
                >
                  <ArrowLeft className="h-4 w-4" /> {t.back}
                </button>
              ) : (
                <div />
              )}

              {step < 3 ? (
                <button
                  onClick={() => setStep((s) => s + 1)}
                  className="btn-primary"
                >
                  {t.next} <ArrowRight className="h-4 w-4" />
                </button>
              ) : (
                <button
                  onClick={handleSubmit}
                  disabled={submitting}
                  className="btn-approve px-6"
                >
                  {submitting ? t.submitting : t.submit}
                </button>
              )}
            </div>
          )}

          {error && (
            <div className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700 ring-1 ring-red-200">
              {error}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Step 1: Personal Information ───────────────────────────────────────── */

function Step1({
  form,
  t,
  updateField,
  formatCnic,
  isUrdu,
}: {
  form: FormData;
  t: Translations;
  updateField: <K extends keyof FormData>(key: K, value: FormData[K]) => void;
  formatCnic: (raw: string) => string;
  isUrdu: boolean;
}) {
  return (
    <div className="space-y-5 animate-slide-up">
      <h2 className={`flex items-center gap-2 ${isUrdu ? "urdu-text" : ""}`}>
        <User className="h-5 w-5 text-blue-600" />
        {t.step1Title}
      </h2>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={`mb-1 block text-xs font-medium text-gray-600 ${isUrdu ? "urdu-text" : ""}`}>
            <span className="inline-flex items-center gap-1"><FileText className="h-3 w-3" />{t.cnic}</span>
          </label>
          <input
            className="input w-full font-mono"
            value={form.cnic}
            onChange={(e) => updateField("cnic", formatCnic(e.target.value))}
            placeholder={t.cnicPlaceholder}
            maxLength={15}
          />
        </div>

        <div>
          <label className={`mb-1 block text-xs font-medium text-gray-600 ${isUrdu ? "urdu-text" : ""}`}>
            <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{t.city}</span>
          </label>
          <select
            className="select w-full"
            value={form.city}
            onChange={(e) => updateField("city", e.target.value)}
          >
            {CITIES.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>

        <div>
          <label className={`mb-1 block text-xs font-medium text-gray-600 ${isUrdu ? "urdu-text" : ""}`}>
            <span className="inline-flex items-center gap-1"><Users className="h-3 w-3" />{t.dependants}</span>
          </label>
          <input
            type="number"
            className="input w-full"
            value={form.dependants}
            min={0}
            max={20}
            onChange={(e) => updateField("dependants", Number(e.target.value))}
          />
        </div>

        <div>
          <label className={`mb-1 block text-xs font-medium text-gray-600 ${isUrdu ? "urdu-text" : ""}`}>
            <span className="inline-flex items-center gap-1"><Briefcase className="h-3 w-3" />{t.occupation}</span>
          </label>
          <select
            className="select w-full"
            value={form.occupation}
            onChange={(e) => updateField("occupation", e.target.value)}
          >
            {OCCUPATIONS.map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}

/* ── Step 2: Document Upload ────────────────────────────────────────────── */

function Step2({
  form,
  t,
  handleFileSelect,
  isUrdu,
}: {
  form: FormData;
  t: Translations;
  handleFileSelect: (field: "utilityFile" | "marksheetFile" | "incomeFile") => (e: React.ChangeEvent<HTMLInputElement>) => void;
  isUrdu: boolean;
}) {
  return (
    <div className="space-y-5 animate-slide-up">
      <h2 className={`flex items-center gap-2 ${isUrdu ? "urdu-text" : ""}`}>
        <Upload className="h-5 w-5 text-blue-600" />
        {t.step2Title}
      </h2>

      <p className={`text-xs text-gray-500 ${isUrdu ? "urdu-text" : ""}`}>
        {t.dropHint}
      </p>

      <div className="space-y-3">
        <DropZone
          icon={<Zap className="h-5 w-5 text-amber-600" />}
          label={t.uploadUtility}
          file={form.utilityFile}
          onChange={handleFileSelect("utilityFile")}
        />
        <DropZone
          icon={<GraduationCap className="h-5 w-5 text-blue-600" />}
          label={t.uploadMarksheet}
          file={form.marksheetFile}
          onChange={handleFileSelect("marksheetFile")}
        />
        <DropZone
          icon={<Banknote className="h-5 w-5 text-green-600" />}
          label={t.uploadIncome}
          file={form.incomeFile}
          onChange={handleFileSelect("incomeFile")}
        />
      </div>
    </div>
  );
}

function DropZone({
  icon,
  label,
  file,
  onChange,
}: {
  icon: React.ReactNode;
  label: string;
  file: File | null;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-3 rounded-lg border-2 border-dashed border-gray-300 bg-gray-50/50 p-4 transition-all hover:border-blue-400 hover:bg-blue-50/30">
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-white ring-1 ring-gray-200">
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-gray-700">{label}</p>
        <p className="text-xs text-gray-400 truncate">
          {file ? file.name : "No file selected"}
        </p>
      </div>
      {file && (
        <CheckCircle2 className="h-5 w-5 shrink-0 text-green-600" />
      )}
      <input
        type="file"
        className="hidden"
        accept=".jpg,.jpeg,.png,.pdf"
        onChange={onChange}
      />
    </label>
  );
}

/* ── Step 3: Review & Submit ────────────────────────────────────────────── */

function Step3({
  form,
  t,
  estimateScore,
  isUrdu,
}: {
  form: FormData;
  t: Translations;
  estimateScore: () => number;
  isUrdu: boolean;
}) {
  const score = estimateScore();
  const band = score >= 60 ? "strong" : score >= 35 ? "moderate" : "low";
  const bandColor = band === "strong" ? "text-green-700" : band === "moderate" ? "text-amber-700" : "text-red-700";
  const docs = [form.utilityFile, form.marksheetFile, form.incomeFile].filter(Boolean).length;

  return (
    <div className="space-y-5 animate-slide-up">
      <h2 className={`flex items-center gap-2 ${isUrdu ? "urdu-text" : ""}`}>
        <CheckCircle2 className="h-5 w-5 text-blue-600" />
        {t.step3Title}
      </h2>

      <div className="grid gap-4 sm:grid-cols-3">
        <div className="metric-card text-center">
          <p className="text-xs text-gray-500">{t.scorePreview}</p>
          <p className={`mt-1 font-mono text-3xl font-bold tabular-nums ${bandColor}`}>
            {score}
          </p>
          <p className={`text-xs font-semibold capitalize ${bandColor}`}>{band}</p>
        </div>

        <div className="metric-card">
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-500">{t.cnic}</span>
              <span className="font-mono">{form.cnic || "—"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">{t.city}</span>
              <span>{form.city}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">{t.dependants}</span>
              <span>{form.dependants}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">{t.occupation}</span>
              <span>{form.occupation}</span>
            </div>
          </div>
        </div>

        <div className="metric-card">
          <p className="mb-2 text-xs font-medium text-gray-500">Documents</p>
          <div className="space-y-1.5 text-sm">
            <div className="flex items-center gap-2">
              <Zap className="h-4 w-4 text-gray-400" />
              <span className={form.utilityFile ? "text-green-700" : "text-gray-400"}>
                {form.utilityFile ? form.utilityFile.name : "Not uploaded"}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <GraduationCap className="h-4 w-4 text-gray-400" />
              <span className={form.marksheetFile ? "text-green-700" : "text-gray-400"}>
                {form.marksheetFile ? form.marksheetFile.name : "Not uploaded"}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Banknote className="h-4 w-4 text-gray-400" />
              <span className={form.incomeFile ? "text-green-700" : "text-gray-400"}>
                {form.incomeFile ? form.incomeFile.name : "Not uploaded"}
              </span>
            </div>
          </div>
          <p className="mt-2 text-xs text-gray-400">{docs}/3 documents attached</p>
        </div>
      </div>

      <div className={`rounded-lg bg-blue-50 p-3 text-xs text-blue-700 ring-1 ring-blue-200 ${isUrdu ? "urdu-text" : ""}`}>
        {t.guidance}
      </div>
    </div>
  );
}

/* ── Success view ───────────────────────────────────────────────────────── */

function SuccessView({
  t,
  score,
  isUrdu,
}: {
  t: Translations;
  score: number | null;
  isUrdu: boolean;
}) {
  return (
    <div className="py-8 text-center animate-slide-up">
      <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-green-100">
        <CheckCircle2 className="h-8 w-8 text-green-600" />
      </div>
      <h2 className={`text-lg font-bold text-green-800 ${isUrdu ? "urdu-text" : ""}`}>
        {t.submitted}
      </h2>
      {score !== null && (
        <div className="mt-4 inline-flex items-center gap-3 rounded-xl bg-green-50 px-6 py-3 ring-1 ring-green-200">
          <span className="text-sm text-green-700">{t.scorePreview}:</span>
          <span className="font-mono text-2xl font-bold text-green-800">{score.toFixed(1)}</span>
        </div>
      )}
      <p className={`mt-4 text-sm text-gray-500 ${isUrdu ? "urdu-text" : ""}`}>
        {t.guidance}
      </p>
    </div>
  );
}
