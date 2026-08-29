ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache python3 py3-pip sqlite

WORKDIR /app
COPY app/ /app/
COPY requirements.txt /app/requirements.txt
COPY run.sh /run.sh
RUN chmod a+x /run.sh

RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

EXPOSE 8099

CMD [ "/run.sh" ]
