"""Configuration classes for the Budget Estimator app."""

from pydantic import Field
from pydantic_settings import BaseSettings


class SheetConfig(BaseSettings):
    """Google Sheets configuration."""

    pricing_guide_sheet_id: str = Field(
        default="",
        description="Google Sheet ID for the pricing guide",
    )
    output_template_sheet_id: str = Field(
        default="",
        description="Google Sheet ID for the output template",
    )
    pricing_guide_tab_name: str = Field(
        default="Sheet1",
        description="Tab name within the pricing guide sheet",
    )
    output_template_tab_name: str = Field(
        default="Sheet1",
        description="Tab name within the output template sheet",
    )
    estimates_sheet_id: str = Field(
        default="",
        description=(
            "Google Sheet ID for the shared estimates workbook. "
            "Each export adds a new tab here instead of creating a new file."
        ),
    )

    model_config = {"env_prefix": "SHEET_"}


class CostConfig(BaseSettings):
    """Cost-related constants that the user can tune."""

    dump_run_cost: float = Field(
        default=120.0,
        description="Cost per dump run in dollars",
    )
    labor_rate_per_hour: float = Field(
        default=60.0,
        description="Labor rate per hour in dollars",
    )
    crew_size: int = Field(
        default=2,
        description="Number of people in the crew",
    )
    plant_delivery_pct: float = Field(
        default=0.07,
        description="Plant delivery cost as a percentage of plant total",
    )
    tax_rate: float = Field(
        default=0.0875,
        description="Sales tax rate",
    )

    model_config = {"env_prefix": "COST_"}


class LLMConfig(BaseSettings):
    """LLM service configuration."""

    openai_api_key: str = Field(
        default="",
        description="OpenAI API key",
    )
    model_name: str = Field(
        default="gpt-4o",
        description="LLM model to use for text interpretation",
    )
    temperature: float = Field(
        default=0.2,
        description="LLM temperature (lower = more deterministic)",
    )
    system_prompt: str = Field(
        default=(
            "You are a landscaping project estimator assistant. "
            "You help translate project descriptions into structured cost estimates. "
            "You must ONLY use materials that exist in the provided pricing guide. "
            "If the description mentions something not in the guide, flag it. "
            "Always respond with valid JSON matching the requested schema."
        ),
        description="Base system prompt for the LLM",
    )

    model_config = {"env_prefix": "LLM_"}


class AppConfig(BaseSettings):
    """General application configuration."""

    app_title: str = Field(
        default="Landscaping Budget Estimator",
        description="Title displayed in the app",
    )
    access_levels: list[str] = Field(
        default=["Easy", "Medium", "Difficult"],
        description="Available access level options",
    )
    default_line_items: list[str] = Field(
        default=[
            "Cleanup/Prep",
            "Design",
            "Fence",
            "Retaining Wall",
            "Plants",
            "Irrigation",
            "Mulch",
            "Misc",
        ],
        description="Default line item categories (overridden by template sheet if available)",
    )

    model_config = {"env_prefix": "APP_"}

