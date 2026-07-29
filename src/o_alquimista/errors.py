"""Erros públicos do domínio de importação."""


class AlquimistaError(Exception):
    """Erro-base apresentado pela CLI."""


class InvalidArchiveError(AlquimistaError):
    """O arquivo fornecido não é um ZIP de save válido."""


class UnsafeArchiveError(InvalidArchiveError):
    """O ZIP contém uma entrada que não pode ser extraída com segurança."""


class ArchiveLimitError(InvalidArchiveError):
    """O ZIP excede um limite de segurança de recursos."""


class IncompleteSaveError(InvalidArchiveError):
    """Não foi encontrada uma raiz com todos os arquivos essenciais."""


class AmbiguousSaveError(InvalidArchiveError):
    """Mais de uma raiz de save igualmente provável foi encontrada."""


class SaveDataError(AlquimistaError):
    """Um arquivo do save não pôde ser interpretado."""


class CampaignMismatchError(AlquimistaError):
    """Snapshots de campanhas diferentes foram comparados sem override."""


class RecordNotFoundError(AlquimistaError):
    """Uma campanha ou snapshot solicitado não existe."""


class UnsafeProvenanceError(AlquimistaError):
    """Um caminho de proveniência não é lógico, relativo e seguro."""


class UnsupportedDatabaseVersionError(AlquimistaError):
    """O banco foi criado por uma versão mais nova do aplicativo."""


class AdvisorUiError(AlquimistaError):
    """A interface local recebeu uma solicitação inválida ou insegura."""
