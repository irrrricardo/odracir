"""Domain-specific extraction profiles for Odracir paper studies."""

from __future__ import annotations

from enum import Enum
from types import MappingProxyType
from typing import Annotated, Final, Mapping

from pydantic import ConfigDict, Field, StringConstraints, computed_field

from odracir.paper_study.models import StrictModel


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class PaperDomain(str, Enum):
    """Coarse paper domains used to select extraction guidance."""

    COMPUTATIONAL_BIO = "computational_biology"
    WET_LAB_MOLECULAR = "wet_lab_molecular"
    CLINICAL_TRIAL = "clinical_trial"
    GENERAL_METHOD = "general_method"


class ScientificLogicMode(str, Enum):
    """Primary scientific argument pattern used to organize extraction."""

    CONTRASTIVE = "contrastive"
    METHODOLOGICAL = "methodological"
    CAUSAL_VALIDATION = "causal_validation"
    PHENOMENOLOGICAL = "phenomenological"


class ExtractionTarget(str, Enum):
    """Domain-specific coverage targets mapped into the canonical v2 models."""

    COMPUTATIONAL_PIPELINE = "computational_pipeline"
    DATASETS_USED = "datasets_used"
    CODE_AVAILABILITY = "code_availability"
    EVALUATION_METRICS = "evaluation_metrics"
    EXPERIMENTAL_SYSTEM = "experimental_system"
    REAGENTS = "reagents"
    PERTURBATION_PROTOCOL = "perturbation_protocol"
    ASSAY_READOUTS = "assay_readouts"
    REPLICATION = "replication"
    PATIENT_COHORT = "patient_cohort"
    STUDY_DESIGN = "study_design"
    CLINICAL_ENDPOINTS = "clinical_endpoints"
    ADVERSE_EVENTS = "adverse_events"
    STATISTICAL_ANALYSIS = "statistical_analysis"
    PROPOSED_METHOD = "proposed_method"
    BASELINES = "baselines"
    ABLATIONS = "ablations"
    LIMITATIONS = "limitations"
    BOUNDARY_CONDITIONS = "boundary_conditions"
    ASSUMPTIONS = "assumptions"
    CAUSAL_EVIDENCE_CHAIN = "causal_evidence_chain"
    SPATIAL_LOCATION = "spatial_location"
    CELL_CELL_COMMUNICATION = "cell_cell_communication"
    SPATIAL_ARCHITECTURE = "spatial_architecture"


class LogicModeProfile(StrictModel):
    """Immutable extraction guidance for one scientific argument pattern."""

    model_config = ConfigDict(frozen=True)

    mode: ScientificLogicMode
    classification_signals: tuple[NonEmptyText, ...] = Field(min_length=1)
    logic_mode_prompt: NonEmptyText
    mandatory_fields: tuple[ExtractionTarget, ...] = Field(default_factory=tuple)


class ExtractionProfile(StrictModel):
    """Immutable instructions for classifying and extracting one paper domain.

    ``mandatory_fields`` are coverage targets, not additional output keys. The
    extraction stage must map supported details into the canonical v2 models
    and must never invent a value when the source does not contain one.
    """

    model_config = ConfigDict(frozen=True)

    domain: PaperDomain
    classification_signals: tuple[NonEmptyText, ...] = Field(
        min_length=1,
        description="Signals indicating that a paper belongs to this domain.",
    )
    domain_prompt: NonEmptyText = Field(
        description="Prompt fragment describing domain-specific extraction priorities.",
    )
    mandatory_fields: tuple[ExtractionTarget, ...] = Field(
        default_factory=tuple,
        description="Coverage targets that the extractor must inspect and account for.",
    )
    logic_mode: ScientificLogicMode | None = None

    @computed_field(return_type=str)
    @property
    def focus_prompt(self) -> str:
        """Compose domain and scientific-logic guidance for this paper."""

        if self.logic_mode is None:
            return self.domain_prompt
        logic_profile = LOGIC_MODE_PROFILES[self.logic_mode]
        return f"{self.domain_prompt}\n\n{logic_profile.logic_mode_prompt}"

    @computed_field(return_type=tuple[ExtractionTarget, ...])
    @property
    def effective_mandatory_fields(self) -> tuple[ExtractionTarget, ...]:
        """Return de-duplicated domain and logic-mode coverage targets."""

        logic_fields = (
            ()
            if self.logic_mode is None
            else LOGIC_MODE_PROFILES[self.logic_mode].mandatory_fields
        )
        return tuple(dict.fromkeys((*self.mandatory_fields, *logic_fields)))


LOGIC_MODE_PROFILES: Final[Mapping[ScientificLogicMode, LogicModeProfile]] = (
    MappingProxyType(
        {
            ScientificLogicMode.CONTRASTIVE: LogicModeProfile(
                mode=ScientificLogicMode.CONTRASTIVE,
                classification_signals=(
                    "same phenotype",
                    "different mechanism",
                    "context dependent",
                    "opposite effect",
                    "opposite conclusion",
                    "in contrast",
                    "whereas",
                    "distinct mechanism",
                    "rather than",
                    "instead of",
                    "alternative mechanism",
                    "does not rely on",
                ),
                logic_mode_prompt=(
                    "Treat contrast as a first-class scientific structure. Separate contrasted "
                    "contexts, systems, conditions, mechanisms, and outcomes into distinct "
                    "StudyUnits. For the same phenotype with different mechanisms, or opposite "
                    "and context-dependent claims involving the same pathway, preserve the "
                    "shared entity, outcome direction, biological or technical context, "
                    "population or experimental system, perturbation, dose, time, and every "
                    "stated boundary condition. Record boundary conditions in "
                    "limitations_and_boundaries and in the relevant StudyUnit statements. Do "
                    "not reconcile contradictory claims or erase negative results. During "
                    "single-paper extraction, never invent a second paper's evidence; retain "
                    "comparison-ready claims so paper A and paper B can be contrasted later."
                ),
                mandatory_fields=(ExtractionTarget.BOUNDARY_CONDITIONS,),
            ),
            ScientificLogicMode.METHODOLOGICAL: LogicModeProfile(
                mode=ScientificLogicMode.METHODOLOGICAL,
                classification_signals=(
                    "benchmark",
                    "baseline",
                    "outperform",
                    "state of the art",
                    "ablation",
                    "runtime",
                    "memory usage",
                    "data efficiency",
                    "under the assumption",
                    "modeling",
                    "mathematical model",
                    "theoretical model",
                    "simulation",
                    "assumption",
                    "parameter sensitivity",
                ),
                logic_mode_prompt=(
                    "Treat this as a methodological comparison or method-evolution argument. "
                    "Extract the proposed method and each baseline separately while preserving "
                    "the shared task, datasets and splits, assumptions, preprocessing, training "
                    "and evaluation protocol, hyperparameters, ablations, and implementation "
                    "requirements. Capture every performance metric with direction, unit, "
                    "uncertainty, and evaluation context, including runtime, memory, sample "
                    "efficiency, or resource cost when reported. Map metrics to "
                    "ResultObservation, and baselines or assumptions to experiment/task or "
                    "method protocol descriptions; do not create undeclared output fields."
                ),
                mandatory_fields=(
                    ExtractionTarget.EVALUATION_METRICS,
                    ExtractionTarget.BASELINES,
                    ExtractionTarget.ASSUMPTIONS,
                ),
            ),
            ScientificLogicMode.CAUSAL_VALIDATION: LogicModeProfile(
                mode=ScientificLogicMode.CAUSAL_VALIDATION,
                classification_signals=(
                    "knockout",
                    "knockdown",
                    "inhibition",
                    "overexpression",
                    "laser ablation",
                    "rescue",
                    "reconstitution",
                    "necessary",
                    "sufficient",
                    "causal mechanism",
                ),
                logic_mode_prompt=(
                    "Reconstruct the causal evidence chain without collapsing its stages. "
                    "Represent correlation or association, perturbation, rescue or reversal, "
                    "and mechanistic explanation as separate StudyUnits in evidentiary order. "
                    "For every stage, extract the intervention, control, experimental system, "
                    "temporal order, dose or intensity, readout, result, and supported claim. "
                    "Record absent, negative, or failed links when the source reports them; if "
                    "a rung such as rescue is not present in the supplied evidence, state that "
                    "boundary without fabricating an experiment. Never upgrade association to "
                    "causation, and link causal claims only to directly supporting Result IDs."
                ),
                mandatory_fields=(
                    ExtractionTarget.CAUSAL_EVIDENCE_CHAIN,
                    ExtractionTarget.PERTURBATION_PROTOCOL,
                ),
            ),
            ScientificLogicMode.PHENOMENOLOGICAL: LogicModeProfile(
                mode=ScientificLogicMode.PHENOMENOLOGICAL,
                classification_signals=(
                    "spatial transcriptomics",
                    "spatial proteomics",
                    "multiplex imaging",
                    "microscopy",
                    "spatial neighborhood",
                    "tissue architecture",
                    "ligand receptor",
                    "cell cell communication",
                    "colocalization",
                    "spatial gradient",
                ),
                logic_mode_prompt=(
                    "Treat spatial organization and observed structure as primary evidence. "
                    "Extract coordinates or anatomical regions, spatial scale and resolution, "
                    "tissue compartments, cell types or states, neighborhoods, gradients, "
                    "morphology or imaging features, spatial statistics, and associations with "
                    "molecular measurements. For ligand-receptor analyses, preserve sender and "
                    "receiver populations, ligand, receptor, spatial proximity, inference "
                    "method, score, and evidence. Map these details into Dataset, Method, "
                    "ResultObservation, Claim, and EvidenceSpan rather than adding fields. Keep "
                    "predicted communication distinct from experimentally validated interaction."
                ),
                mandatory_fields=(
                    ExtractionTarget.SPATIAL_LOCATION,
                    ExtractionTarget.CELL_CELL_COMMUNICATION,
                    ExtractionTarget.SPATIAL_ARCHITECTURE,
                ),
            ),
        }
    )
)


DOMAIN_PROFILES: Final[Mapping[PaperDomain, ExtractionProfile]] = MappingProxyType(
    {
        PaperDomain.COMPUTATIONAL_BIO: ExtractionProfile(
            domain=PaperDomain.COMPUTATIONAL_BIO,
            classification_signals=(
                "computational biology",
                "bioinformatics",
                "transcriptomics",
                "gene regulatory network",
                "network biology",
                "machine learning",
                "deep learning",
                "foundation model",
                "perturbation prediction",
            ),
            domain_prompt=(
                "Treat this as a computational biology paper. Reconstruct preprocessing, "
                "normalization, feature construction, model or algorithm steps, parameter "
                "settings, and train/validation/test splits in execution order. Preserve "
                "dataset names and versions, biological scope, baselines, ablations, code "
                "availability, and quantitative results such as AUC, accuracy, calibration, "
                "Pearson or Spearman correlation, effect sizes, confidence intervals, and "
                "p-values. Keep computational predictions distinct from wet-lab validation. "
                "If a target is not reported, leave it absent rather than infer it."
            ),
            mandatory_fields=(
                ExtractionTarget.COMPUTATIONAL_PIPELINE,
                ExtractionTarget.DATASETS_USED,
                ExtractionTarget.EVALUATION_METRICS,
                ExtractionTarget.CODE_AVAILABILITY,
            ),
        ),
        PaperDomain.WET_LAB_MOLECULAR: ExtractionProfile(
            domain=PaperDomain.WET_LAB_MOLECULAR,
            classification_signals=(
                "wet lab",
                "cell biology",
                "molecular biology",
                "cancer biology",
                "developmental biology",
                "neuroscience",
                "immunology",
                "mechanobiology",
                "morphogenesis",
                "cell line",
                "reagent",
                "assay",
            ),
            domain_prompt=(
                "Treat this as a wet-lab molecular or cellular biology paper. Extract the "
                "experimental system, species, tissue, cell line, sample preparation, "
                "controls, reagents, perturbations, dose, duration, temperature, selection "
                "timeline, and assay readouts with their units. Preserve biological and "
                "technical replicate counts, sample sizes, statistical tests, and the exact "
                "conditions under which each result was observed. Distinguish measured "
                "results from mechanistic interpretation, and do not manufacture missing "
                "protocol details."
            ),
            mandatory_fields=(
                ExtractionTarget.EXPERIMENTAL_SYSTEM,
                ExtractionTarget.REAGENTS,
                ExtractionTarget.PERTURBATION_PROTOCOL,
                ExtractionTarget.ASSAY_READOUTS,
                ExtractionTarget.REPLICATION,
            ),
        ),
        PaperDomain.CLINICAL_TRIAL: ExtractionProfile(
            domain=PaperDomain.CLINICAL_TRIAL,
            classification_signals=(
                "clinical trial",
                "clinical study",
                "patient cohort",
                "human participants",
                "inclusion criteria",
                "exclusion criteria",
                "treatment regimen",
                "clinical endpoint",
                "adverse event",
                "epidemiology",
            ),
            domain_prompt=(
                "Treat this as a clinical or epidemiological study. Extract study design, "
                "registration when reported, recruitment setting, cohort size, inclusion and "
                "exclusion criteria, demographics, intervention or exposure, comparator, "
                "dosage and follow-up, attrition, primary and secondary endpoints, adverse "
                "events, confounders, and subgroup analyses. Preserve effect sizes, confidence "
                "intervals, p-values, and adjusted versus unadjusted analyses. Do not broaden "
                "causal or clinical claims beyond the stated design and population."
            ),
            mandatory_fields=(
                ExtractionTarget.STUDY_DESIGN,
                ExtractionTarget.PATIENT_COHORT,
                ExtractionTarget.CLINICAL_ENDPOINTS,
                ExtractionTarget.ADVERSE_EVENTS,
                ExtractionTarget.STATISTICAL_ANALYSIS,
            ),
        ),
        PaperDomain.GENERAL_METHOD: ExtractionProfile(
            domain=PaperDomain.GENERAL_METHOD,
            classification_signals=(
                "proposed method",
                "framework",
                "algorithm",
                "benchmark",
                "baseline",
                "ablation",
                "performance",
                "modeling",
                "mathematical model",
                "theoretical model",
                "simulation",
                "review",
            ),
            domain_prompt=(
                "Focus on the proposed method's objective, assumptions, components, inputs, "
                "outputs, protocol, and implementation requirements. Extract evaluation tasks "
                "and datasets, baseline methods, metrics, quantitative comparisons, ablation "
                "studies, resource or cost measurements, failure modes, and stated limitations. "
                "Preserve the conditions and evidence supporting every result. Do not force "
                "clinical or biological fields when the paper does not report them."
            ),
            mandatory_fields=(
                ExtractionTarget.PROPOSED_METHOD,
                ExtractionTarget.BASELINES,
                ExtractionTarget.EVALUATION_METRICS,
                ExtractionTarget.ABLATIONS,
                ExtractionTarget.LIMITATIONS,
            ),
        ),
    }
)


_DOMAIN_ALIASES: Final[Mapping[str, PaperDomain]] = MappingProxyType(
    {
        "computational_bio": PaperDomain.COMPUTATIONAL_BIO,
        "bioinformatics": PaperDomain.COMPUTATIONAL_BIO,
        "biomedical_ai": PaperDomain.COMPUTATIONAL_BIO,
        "experimental_biomedical": PaperDomain.WET_LAB_MOLECULAR,
        "wet_lab": PaperDomain.WET_LAB_MOLECULAR,
        "molecular_biology": PaperDomain.WET_LAB_MOLECULAR,
        "cell_biology": PaperDomain.WET_LAB_MOLECULAR,
        "clinical": PaperDomain.CLINICAL_TRIAL,
        "clinical_research": PaperDomain.CLINICAL_TRIAL,
        "clinical_study": PaperDomain.CLINICAL_TRIAL,
        "epidemiology": PaperDomain.CLINICAL_TRIAL,
        "general": PaperDomain.GENERAL_METHOD,
        "generic": PaperDomain.GENERAL_METHOD,
        "method": PaperDomain.GENERAL_METHOD,
        "machine_learning": PaperDomain.GENERAL_METHOD,
    }
)


_DOMAIN_KEYWORDS: Final[tuple[tuple[PaperDomain, tuple[str, ...]], ...]] = (
    (
        PaperDomain.CLINICAL_TRIAL,
        (
            "clinical trial",
            "clinical study",
            "clinical research",
            "epidemiology",
            "patient cohort",
            "human cohort",
        ),
    ),
    (
        PaperDomain.COMPUTATIONAL_BIO,
        (
            "computational biology",
            "computational pathology",
            "bioinformatics",
            "transcriptomics",
            "gene regulatory network",
            "network biology",
            "machine learning",
            "deep learning",
            "foundation model",
            "generative ai",
            "perturbation prediction",
        ),
    ),
    (
        PaperDomain.WET_LAB_MOLECULAR,
        (
            "wet lab",
            "molecular biology",
            "cell biology",
            "cancer biology",
            "developmental biology",
            "neuroscience",
            "immunology",
            "mechanobiology",
            "morphogenesis",
            "bioelectric",
            "mitochondrial biology",
        ),
    ),
)


def get_profile_for_domain(
    domain: PaperDomain | str | None,
    logic_mode: ScientificLogicMode | str | None = None,
) -> ExtractionProfile:
    """Resolve domain guidance and optionally compose logic-mode requirements."""

    resolved = _resolve_domain(domain)
    resolved_logic_mode = resolve_logic_mode(logic_mode)
    return DOMAIN_PROFILES[resolved].model_copy(
        update={"logic_mode": resolved_logic_mode}
    )


def get_logic_mode_profile(
    logic_mode: ScientificLogicMode | str,
) -> LogicModeProfile:
    """Resolve a required scientific-logic profile or raise ``ValueError``."""

    resolved = resolve_logic_mode(logic_mode)
    if resolved is None:
        raise ValueError(f"Unknown scientific logic mode: {logic_mode!r}")
    return LOGIC_MODE_PROFILES[resolved]


def resolve_logic_mode(
    logic_mode: ScientificLogicMode | str | None,
) -> ScientificLogicMode | None:
    """Normalize a logic-mode hint without guessing on unknown values."""

    if isinstance(logic_mode, ScientificLogicMode):
        return logic_mode
    if not isinstance(logic_mode, str):
        return None
    normalized = "_".join(logic_mode.strip().casefold().replace("-", " ").split())
    if not normalized:
        return None
    try:
        return ScientificLogicMode(normalized)
    except ValueError:
        return None


def _resolve_domain(domain: PaperDomain | str | None) -> PaperDomain:
    if isinstance(domain, PaperDomain):
        return domain
    if not isinstance(domain, str):
        return PaperDomain.GENERAL_METHOD

    normalized_label = _normalize_domain_label(domain)
    if not normalized_label:
        return PaperDomain.GENERAL_METHOD
    normalized_value = normalized_label.replace(" ", "_")
    try:
        return PaperDomain(normalized_value)
    except ValueError:
        alias = _DOMAIN_ALIASES.get(normalized_value)
        if alias is not None:
            return alias

    for candidate, keywords in _DOMAIN_KEYWORDS:
        if any(keyword in normalized_label for keyword in keywords):
            return candidate
    return PaperDomain.GENERAL_METHOD


def _normalize_domain_label(value: str) -> str:
    separators = str.maketrans({character: " " for character in "_-/;,|"})
    return " ".join(value.strip().casefold().translate(separators).split())


def _validate_profile_registry() -> None:
    if set(DOMAIN_PROFILES) != set(PaperDomain):
        raise RuntimeError("DOMAIN_PROFILES must define every PaperDomain exactly once")
    for domain, profile in DOMAIN_PROFILES.items():
        if profile.domain is not domain:
            raise RuntimeError(f"Profile key and domain differ for {domain.value}")
    if set(LOGIC_MODE_PROFILES) != set(ScientificLogicMode):
        raise RuntimeError(
            "LOGIC_MODE_PROFILES must define every ScientificLogicMode exactly once"
        )
    for mode, profile in LOGIC_MODE_PROFILES.items():
        if profile.mode is not mode:
            raise RuntimeError(f"Profile key and mode differ for {mode.value}")


_validate_profile_registry()
