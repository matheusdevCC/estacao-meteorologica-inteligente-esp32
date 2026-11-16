# Evidencias para o GitHub - API, layout e geometria 2D

## Preparacao

1. Abra `codigo/main.py` no Thonny, com MicroPython (ESP32).
2. Como o AO do MQ-135 ainda nao esta eletricamente validado, deixe `MQ_MODO = 'demonstracao'`. O painel mostrara 0 explicitamente como demonstracao, nao como leitura real.
3. Pressione F5 e aguarde o ESP32 criar a rede `Estacao-ESP32`.
4. Conecte o notebook a essa rede e use a senha de demonstracao `Estacao2026`.
5. Todos os enderecos abaixo somente funcionam conectado ao Wi-Fi do ESP32.

## Prints recomendados

| Evidencia | URL | O que mostrar |
| --- | --- | --- |
| Documentacao da API | `http://192.168.4.1/docs` | Tabela GET e JSON obtido ao vivo |
| Resposta JSON | `http://192.168.4.1/api` | Dados das leituras, campos nulos e status |
| Estado da estacao | `http://192.168.4.1/api/status` | ID, versao e tempo de atividade |
| Geometria analitica | `http://192.168.4.1/api/geometria?x=30&y=40` | Vetor (30,40), distancia 50 e angulo 53.13 graus |
| Layout para o cidadao | `http://192.168.4.1/` | Indicadores e menu de navegacao |
| Plano interativo | `http://192.168.4.1/#mapa` | Clique no plano e veja o resultado variar |

## Sobre o mockup

O arquivo `docs/mockup-cidadao.html` funciona sem a placa, mas **usa dados ficticios**, e o proprio layout avisa que nao se trata de uma leitura real. Ele serve apenas como evidencia de planejamento de interface. Para evidenciar funcionamento real, fotografe a pagina aberta no ESP32.

## Restricoes tecnicas

- `GET /api` fornece leituras atuais; nao ha banco de dados, historico persistente nem API publica na internet.
- O plano 2D usa coordenadas arbitrarias em escala didatica; nao e um mapa geografico/GPS.
- A pressao do BMP280 continua em diagnostico.
- O valor 0 no modo demonstracao nao veio do MQ-135; no JSON, confira os campos mq_origem=demonstracao e mq_status. A leitura ADC real so deve ser ativada com AO adaptado a 3,3 V no GPIO32; mesmo assim nao representa ppm.

## Publicar com GitHub Desktop

Copie os arquivos `codigo/main.py`, `README.md`, `docs/mockup-cidadao.html` e `docs/GUIA_EVIDENCIAS_API_MAPA.md` para suas respectivas pastas no clone local do repositório. Em GitHub Desktop, revise Changes, use Commit to main e Push origin.
