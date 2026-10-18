# Notas sobre concorrentes (interno — não é texto de produto)

Fontes consultadas em 2026-10-18: página do OpendTect (dGB Earth Sciences), product sheet RokDoc v14 e nota de lançamento RokDoc 2026.2 (Ikon Science). Apenas factos publicados; sem comparações de desempenho (spec §1.2).

## OpendTect (dGB Earth Sciences)
- Modelo **open-core**: núcleo GPL-3.0; OpendTect Pro e pacote de Machine Learning comerciais; a licença Pro permite a parceiros distribuir plugins fechados.
- Foco: visualização e interpretação sísmica 2D/3D/4D, GPR; integração Python para scripts, modelos e IA; plugins em C++ ou Python.
- Confiança construída com: manual do programador, biblioteca/FAQ, webinars, Discord e mailing list, histórico desde 1995, lista de plataformas suportadas.
- A página não descreve validação científica publicada.

## RokDoc (Ikon Science)
- Interpretação quantitativa: física de rochas (biblioteca de modelos, modelação 1D–4D), AVO, previsão de pressão de poros, geomecânica 3D, inversão.
- Ligação direta ao Petrel e a software de terceiros; importa LAS, DLIS, SEG-Y, grelhas ECLIPSE, etc.
- QC automático, edição de logs e cross-plots, incerteza probabilística, análise multi-cenário.
- 2026.2: QC de inversões com vários filtros numa sessão, persistência de escalas entre sessões, deteção de leitor SEG-Y errado, limites de memória configuráveis, link Petrosys.
- Os materiais consultados não descrevem trilho de auditoria por cálculo.

## Lições aplicadas ao GeoReservoir
1. **Open-core é um modelo comprovado no setor** → opção destacada no ADR-0002 (decisão do fundador).
2. **Python e plugins** são esperados → manter núcleo puro e API estável; preparar registo de módulos para plugins (Fase 3).
3. **Interoperabilidade é condição de entrada** (Petrel, LAS/DLIS/SEG-Y) → Fase 2 deve priorizar LAS e surveys com proveniência.
4. **QC e cenários** são valorizados → `CalculationRecord` já suporta comparar cenários por `inputs_hash`; Monte Carlo P10/P50/P90 na Fase 1.
5. **Comunidade e formação constroem confiança** → dossiê de validação público + material para universidades (ISPTEC/SPE) como canal inicial.
6. **Espaço livre observado:** auditabilidade por cálculo e validação publicada caso a caso não aparecem nos materiais consultados — confirma a tese 1.1, sem afirmar que os concorrentes não o fazem internamente.
