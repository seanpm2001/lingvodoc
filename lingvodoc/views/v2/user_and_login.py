__author__ = 'alexander'

from lingvodoc.exceptions import CommonException
from lingvodoc.models import (
    BaseGroup,
    Client,
    DBSession,
    Email,
    Group,
    Passhash,
    User
)
from lingvodoc.views.v2.utils import (
    get_user_by_client_id
)

from pyramid.httpexceptions import (
    HTTPBadRequest,
    HTTPConflict,
    HTTPFound,
    HTTPNotFound,
    HTTPInternalServerError,
    HTTPOk,
    HTTPUnauthorized
)
from pyramid.renderers import render_to_response
from pyramid.response import Response
from pyramid.security import (
    authenticated_userid,
    forget,
    remember
)
from pyramid.view import view_config

from sqlalchemy import (
    or_
)

import datetime
import logging
import json
from lingvodoc.views.v2.utils import add_user_to_group
from pyramid.request import Request

log = logging.getLogger(__name__)


@view_config(route_name='signup', renderer='templates/signup.pt', request_method='GET')
def signup_get(request):
    variables = {'auth': authenticated_userid(request)}
    return render_to_response('templates/signup.pt', variables, request=request)


@view_config(route_name='signup', renderer='json', request_method='POST')
def signup_post(request):  # tested
    try:
        req = request.json_body
        login = req['login']
        name = req['name']
        email = req['email']
        password = req['password']

        day = req.get('day')
        month = req.get('month')
        year = req.get('year')
        if day is None or month is None or year is None:
            request.response.status = HTTPBadRequest.code
            return {'Error': "day, month or year of the birth is missing"}
        # birthday = datetime.datetime.strptime(day + month + year, "%d%m%Y").date()
        try:
            day = int(day)
            month = int(month)
            year = int(year)
            birthday = datetime.date(year, month, day)
        except ValueError:
            request.response.status = HTTPBadRequest.code
            return {'Error': "Invalid birthday"}

        if DBSession.query(User).filter_by(login=login).first():
            raise CommonException("The user with this login is already registered")
        if DBSession.query(Email).filter_by(email=email).first():
            raise CommonException("The user with this email is already registered")
        new_user = User(login=login, name=name, created_at=datetime.datetime.utcnow(), intl_name=login, birthday=birthday, is_active=True)
        pwd = Passhash(password=password)
        email = Email(email=email)
        new_user.password = pwd
        new_user.email = email
        DBSession.add(new_user)
        basegroups = []
        basegroups += [DBSession.query(BaseGroup).filter_by(name="Can create dictionaries").first()]
        basegroups += [DBSession.query(BaseGroup).filter_by(name="Can create languages").first()]
        basegroups += [DBSession.query(BaseGroup).filter_by(name="Can create organizations").first()]
        basegroups += [DBSession.query(BaseGroup).filter_by(name="Can create translation strings").first()]
        groups = []
        for base in basegroups:
            groups += [DBSession.query(Group).filter_by(subject_override=True, base_group_id=base.id).first()]
        for group in groups:
            add_user_to_group(new_user, group)
        DBSession.flush()
        return {}

    except KeyError as e:
        request.response.status = HTTPBadRequest.code
        return {'status': request.response.status, 'error': str(e)}

    except CommonException as e:
        request.response.status = HTTPConflict.code
        return {'status': request.response.status, 'error': str(e)}

    except ValueError as e:
        request.response.status = HTTPConflict.code
        return {'status': request.response.status, 'error': str(e)}


@view_config(route_name='login', renderer='templates/login.pt', request_method='GET')
def login_get(request):
    variables = {'auth': authenticated_userid(request)}
    return render_to_response('templates/login.pt', variables, request=request)


@view_config(route_name='login', request_method='POST', renderer='json')
def login_post(request):  # tested
    # next = request.params.get('next') or request.route_url('home')
    login = request.POST.get('login', '')
    password = request.POST.get('password', '')
    # print(login)
    log.debug(login)
    user = DBSession.query(User).filter_by(login=login).first()
    if user and user.check_password(password):
        client = Client(user_id=user.id)
        user.clients.append(client)
        DBSession.add(client)
        DBSession.flush()
        headers = remember(request, principal=client.id)
        response = Response()
        response.headers = headers
        locale_id = user.default_locale_id
        if not locale_id:
            locale_id = 1
        response.set_cookie(key='locale_id', value=str(locale_id))
        response.set_cookie(key='client_id', value=str(client.id))
        headers = remember(request, principal=client.id)
        # return HTTPFound(location=next, headers=response.headers)
        return HTTPOk(headers=response.headers, json_body={})
        # return {}
    return HTTPUnauthorized(location=request.route_url('login'))


@view_config(route_name='signin', renderer='json', request_method='POST')
def signin(request):
    req = request.json_body
    login = req['login']
    password = req['password']
    # login = request.POST.get('login', '')
    # password = request.POST.get('password', '')
    desktop = req.get('desktop', False)

    user = DBSession.query(User).filter_by(login=login).first()
    if user and user.check_password(password):
        client = Client(user_id=user.id, is_browser_client=not desktop)
        user.clients.append(client)
        DBSession.add(client)
        DBSession.flush()
        headers = remember(request, principal=client.id)
        response = Response()
        response.headers = headers
        locale_id = user.default_locale_id
        if not locale_id:
            locale_id = 1
        response.set_cookie(key='locale_id', value=str(locale_id))
        response.set_cookie(key='client_id', value=str(client.id))
        result = dict()
        result['client_id'] = client.id
        request.response.status = HTTPOk.code
        # request.response.headers = headers
        # return response
        return HTTPOk(headers=response.headers, json_body=result)
        # return result
    return HTTPUnauthorized(location=request.route_url('login'))


@view_config(route_name='sync_signin', renderer='json', request_method='POST')
def sync_signin(request):
    req = request.json_body
    login = req['login']
    password = req['password']

    user = DBSession.query(User).filter_by(login=login).first()
    if user and user.check_password(password):
        request.response.status = HTTPOk.code
        return HTTPOk(json_body={})
    return HTTPUnauthorized(location=request.route_url('login'))


@view_config(route_name='desk_signin', renderer='json', request_method='POST')
def desk_signin(request):
    import requests
    req = request.json_body
    login = req['login']
    password = req['password']
    settings = request.registry.settings

    path = settings['desktop']['central_server'] + 'signin'
    session = requests.Session()
    session.headers.update({'Connection': 'Keep-Alive'})
    adapter = requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=1, max_retries=10)
    session.mount('http://', adapter)
    status = session.post(path, json=req)
    client_id = status.json()['client_id']
    cookies = status.cookies.get_dict()
    with open('authentication_data.json', 'w') as f:
        f.write(json.dumps(cookies))
    if status.status_code == 200:
        path = request.route_url('basic_sync')
        subreq = Request.blank(path)
        subreq.method = 'POST'
        sub_headers = {'Cookie': request.headers['Cookie']}
        subreq.headers = sub_headers
        resp = request.invoke_subrequest(subreq)
        if resp.status_code == 200:
            headers = remember(request, principal=client_id)
            response = Response()
            response.headers = headers
            locale_id = cookies['locale_id']
            response.set_cookie(key='locale_id', value=str(locale_id))
            response.set_cookie(key='client_id', value=str(client_id))
            result = dict()
            result['client_id'] = client_id
            request.response.status = HTTPOk.code
            # request.response.headers = headers
            # return response
            return HTTPOk(headers=response.headers, json_body=result)
        # return result
    return HTTPUnauthorized(location=request.route_url('login'))




# @view_config(route_name='test', renderer='json', request_method='GET')
# def test(request):
#     client = Client(user_id=1, counter = 2147483647123)
#     DBSession.add(client)
#     DBSession.flush()
#     return {}


@view_config(route_name='cheatlogin', request_method='POST', renderer='json')
def login_cheat(request):  # TODO: test
    next = request.params.get('next') or request.route_url('dashboard')
    login = request.json_body.get('login', '')
    passwordhash = request.json_body.get('passwordhash', '')
    log.debug("Logging in with cheat method:" + login)
    user = DBSession.query(User).filter_by(login=login).first()
    if user and user.password.hash == passwordhash:
        log.debug("Login successful")
        client = Client(user_id=user.id)
        user.clients.append(client)
        DBSession.add(client)
        DBSession.flush()
        headers = remember(request, principal=client.id)
        response = Response()
        response.headers = headers
        locale_id = user.default_locale_id
        if not locale_id:
            locale_id = 1
        response.set_cookie(key='locale_id', value=str(locale_id))
        response.set_cookie(key='client_id', value=str(client.id))
        headers = remember(request, principal=client.id)
        return response

    log.debug("Login unsuccessful for " + login)
    return HTTPUnauthorized(location=request.route_url('login'))


@view_config(route_name='logout', renderer='json')
def logout_any(request):  # tested
    headers = forget(request)
    return HTTPOk(headers=headers, json_body={})


@view_config(route_name='profile', renderer='templates/profile.pt', request_method='GET')
def profile_get(request):
    client_id = authenticated_userid(request)
    user = get_user_by_client_id(client_id)
    if user is None:
        response = Response()
        return HTTPFound(location=request.route_url('login'), headers=response.headers)
    variables = {'client_id': client_id, 'user': user }
    return render_to_response('templates/profile.pt', variables, request=request)


@view_config(route_name='users', renderer='json', request_method='GET')
def users_list(request):  # tested
    response = dict()
    search = None
    try:
        search = request.params.get('search')
    except:
        pass
    users_temp = DBSession.query(User).join(User.email)
    users = []
    if search:
        name = search + '%'
        users_temp = users_temp.filter(or_(
            User.name.startswith(name),
            User.login.startswith(name),
            User.intl_name.startswith(name),
            Email.email.startswith(name)
        ))
    for user in users_temp:
        users += [{'id': user.id, 'name': user.name, 'login': user.login, 'intl_name': user.intl_name}]

    response['users'] = users
    request.response.status = HTTPOk.code

    return response


@view_config(route_name='get_user_info', renderer='json', request_method='GET')
def get_user_info(request):  # tested
    response = dict()
    client_id = request.params.get('client_id')
    user_id = request.params.get('user_id')
    if client_id:
        client = DBSession.query(Client).filter_by(id=client_id).first()
        if not client:

            request.response.status = HTTPNotFound.code
            return {'error': str("No such client in the system")}
        user = DBSession.query(User).filter_by(id=client.user_id).first()
        if not user:
            request.response.status = HTTPNotFound.code
            return {'error': str("No such user in the system")}
    elif user_id:
        user = DBSession.query(User).filter_by(id=user_id).first()
        if not user:
            request.response.status = HTTPNotFound.code
            return {'error': str("No such user in the system")}
    else:
        client = DBSession.query(Client).filter_by(id=authenticated_userid(request)).first()
        if not client:
            request.response.status = HTTPNotFound.code
            return {'error': str("No such client in the system")}
        user = DBSession.query(User).filter_by(id=client.user_id).first()
        if not user:
            request.response.status = HTTPNotFound.code
            return {'error': str("No such user in the system")}
    response['id']= user.id
    response['login'] = user.login
    response['name'] = user.name
    response['intl_name'] = user.intl_name
    response['default_locale_id'] = user.default_locale_id
    response['birthday'] = str(user.birthday)
    response['created_at'] = user.created_at
    response['is_active'] = user.is_active
    if user.email:
        response['email'] = user.email.email
    meta = None
    if user.additional_metadata:
        meta = user.additional_metadata
    if meta and meta.get('about'):
        response['about'] = meta['about']
    organizations = []
    for organization in user.organizations:
        organizations += [{'organization_id':organization.id}]
    response['organizations'] = organizations
    request.response.status = HTTPOk.code
    return response


@view_config(route_name='get_user_info', renderer='json', request_method='PUT')
def edit_user_info(request):  # TODO: test
    from passlib.hash import bcrypt
    response = dict()

    req = request.json_body
    client_id = req.get('client_id')
    user_id = req.get('user_id')
    user = None
    if client_id:
        client = DBSession.query(Client).filter_by(id=client_id).first()
        if not client:

            request.response.status = HTTPNotFound.code
            return {'error': str("No such client in the system")}
        user = DBSession.query(User).filter_by(id=client.user_id).first()
        user_id = client.user_id
        if not user:

            request.response.status = HTTPNotFound.code
            return {'error': str("No such user in the system")}
    else:
        user = DBSession.query(User).filter_by(id=user_id).first()
        if not user:

            request.response.status = HTTPNotFound.code
            return {'error': str("No such user in the system")}
    new_password = req.get('new_password')
    old_password = req.get('old_password')

    if new_password:
        if not old_password:
            request.response.status = HTTPBadRequest.code
            return {'error': str("Need old password to confirm")}
        old_hash = DBSession.query(Passhash).filter_by(user_id=user_id).first()
        if old_hash:
            if not user.check_password(old_password):
                request.response.status = HTTPBadRequest.code
                return {'error': str("Wrong password")}
            else:
                old_hash.hash = bcrypt.encrypt(new_password)
        else:
            request.response.status = HTTPInternalServerError.code
            return {'error': str("User has no password")}

    name = req.get('name')
    if name:
        user.name = name
    default_locale_id = req.get('default_locale_id')
    if default_locale_id:
        user.default_locale_id = default_locale_id
    birthday = req.get('birthday')
    if birthday:
        try:
            year, month, day = birthday.split('-')
            user.birthday = datetime.date(int(year), int(month), int(day))
        except ValueError:
            request.response.status = HTTPBadRequest.code
            return {'Error': "Invalid birthday"}
    email = req.get('email')
    if email:
        if user.email:
            user.email.email = email
        else:
            new_email = Email(user=user, email=email)
            DBSession.add(new_email)
            DBSession.flush()
    about = req.get('about')
    if about:
        meta = dict()
        if user.additional_metadata:
            meta = user.additional_metadata
        meta['about'] = about
        user.additional_metadata = meta
    # response['is_active']=str(user.is_active)
    request.response.status = HTTPOk.code
    return response